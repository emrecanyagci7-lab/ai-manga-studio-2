"""AI Manga Studio backend."""
import os
import uuid
import json
import asyncio
import logging
import io
import re
from urllib.parse import quote as urlquote
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Header, Query
from fastapi.responses import StreamingResponse, Response
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Local imports
from ai_service import generate_json, generate_image
from storage_service import init_storage, upload_image, get_object, APP_NAME
from prompts import (
    STORY_PLAN_SYSTEM, STORY_PLAN_USER,
    SCENE_DECOMP_SYSTEM, SCENE_DECOMP_USER,
    IMAGE_PROMPT_TEMPLATE, CHARACTER_PORTRAIT_PROMPT,
)

DEFAULT_PANEL_CAP = 8
HARD_PANEL_CAP = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]

app = FastAPI(title="AI Manga Studio")
api = APIRouter(prefix="/api")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex


# ---------------- Models ----------------
class CreateMangaIn(BaseModel):
    idea: str = Field(min_length=8, max_length=2000)
    genre: str = "Fantasy"
    art_style: str = "Manga-inspired"
    chapter_count: int = Field(default=5, ge=1, le=20)
    creativity: str = "balanced"  # conservative | balanced | wild
    client_id: str = Field(min_length=1)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class PublishIn(BaseModel):
    is_published: bool = True


class BubbleModel(BaseModel):
    id: str
    text: str = ""
    type: str = "speech"
    character: str = ""
    x: float = 0.1
    y: float = 0.1
    width: float = 0.3
    height: float = 0.15


class BubbleIn(BaseModel):
    bubbles: List[BubbleModel]


class PanelCapIn(BaseModel):
    max_panels_per_chapter: int = Field(ge=1, le=HARD_PANEL_CAP)


class BatchGenerateIn(BaseModel):
    chapter_ids: List[str] = Field(min_length=1, max_length=20)


async def _bump_stats(manga_id: str, text_calls: int = 0, image_calls: int = 0, panels: int = 0, chapters: int = 0):
    """Increment usage counters on the manga doc (best-effort)."""
    inc = {}
    if text_calls: inc["stats.text_calls"] = text_calls
    if image_calls: inc["stats.image_calls"] = image_calls
    if panels: inc["stats.panels_generated"] = panels
    if chapters: inc["stats.chapters_generated"] = chapters
    if not inc:
        return
    await db.mangas.update_one({"id": manga_id}, {"$inc": inc, "$set": {"updated_at": now_iso()}})


def _sanitize_ai_error(e: Exception) -> str:
    """Kullanıcı dostu hata mesajı döndür; teknik ayrıntıları gizle."""
    msg = str(e)
    low = msg.lower()
    if "google_api_key" in low or "api_key" in low or "api key" in low:
        return "Google API anahtarı ayarlanmamış. Lütfen /app/backend/.env dosyasına GOOGLE_API_KEY ekle."
    if "quota" in low or "429" in low or "rate limit" in low or "resource_exhausted" in low:
        return "Yapay zekâ servisi geçici olarak meşgul (kota limiti). Lütfen kısa süre sonra tekrar deneyin."
    if "timeout" in low or "timed out" in low:
        return "Yapay zekâ servisi zaman aşımına uğradı. Lütfen tekrar deneyin."
    if "pollinations" in low or "connection" in low:
        return "Görsel üretim servisine ulaşılamadı. Lütfen tekrar deneyin."
    return "Yapay zekâ üretimi başarısız oldu. Lütfen tekrar deneyin."


# ---------------- Startup ----------------
@app.on_event("startup")
async def startup():
    try:
        await asyncio.to_thread(init_storage)
    except Exception as e:
        logger.error(f"Storage init failed at startup: {e}")
    # Reconcile stuck jobs from previous run
    try:
        stuck = await db.generation_jobs.update_many(
            {"status": {"$in": ["queued", "running"]}},
            {"$set": {"status": "error", "error": "Sunucu yeniden başlatıldığı için iş yarıda kesildi", "updated_at": now_iso()}},
        )
        if stuck.modified_count:
            logger.warning(f"Reconciled {stuck.modified_count} stuck jobs")
        await db.chapters.update_many({"status": "generating"}, {"$set": {"status": "error"}})
        await db.mangas.update_many({"plan_status": "planning"}, {"$set": {"plan_status": "error"}})
    except Exception as e:
        logger.error(f"Job reconciliation failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    mongo_client.close()


# ---------------- Health ----------------
@api.get("/")
async def root():
    return {"service": "AI Manga Studio", "ok": True}


@api.get("/health")
async def health():
    return {"ok": True, "time": now_iso()}


# ---------------- Files ----------------
@api.get("/files/{path:path}")
async def download_file(path: str):
    try:
        data, ct = await asyncio.to_thread(get_object, path)
    except Exception as e:
        logger.error(f"File download failed for {path}: {e}")
        raise HTTPException(status_code=404, detail="Bulunamadı")
    return Response(content=data, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})


@api.post("/upload/character-reference")
async def upload_character_ref(file: UploadFile = File(...), client_id: str = Form(...)):
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png").lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        raise HTTPException(400, "Desteklenmeyen görsel türü")
    data = await file.read()
    storage_path = await asyncio.to_thread(upload_image, data, f"user-refs/{client_id}", ext)
    return {"storage_path": storage_path, "url": f"/api/files/{storage_path}"}


# ---------------- Manga: create + plan (ASYNC JOB) ----------------
async def _run_plan_generation(job_id: str, manga_id: str, body_dict: dict):
    """Background worker generating the story bible + characters + chapters."""
    async def update(progress: int, status: str = "running", error: Optional[str] = None):
        patch = {"progress": progress, "status": status, "updated_at": now_iso()}
        if error:
            patch["error"] = error
        await db.generation_jobs.update_one({"id": job_id}, {"$set": patch})

    try:
        await update(5, "running")
        session = f"plan-{manga_id}"
        plan = await generate_json(
            STORY_PLAN_SYSTEM,
            STORY_PLAN_USER.format(
                idea=body_dict["idea"],
                genre=body_dict["genre"],
                art_style=body_dict["art_style"],
                chapter_count=body_dict["chapter_count"],
                creativity=body_dict["creativity"],
            ),
            session_id=session,
        )
        await _bump_stats(manga_id, text_calls=1)
        await update(70, "running")

        # Fill in manga details
        await db.mangas.update_one({"id": manga_id}, {"$set": {
            "title": plan.get("title", "İsimsiz Manga"),
            "logline": plan.get("logline", ""),
            "synopsis": plan.get("synopsis", ""),
            "world": plan.get("world", {}),
            "themes": plan.get("themes", []),
            "plan_status": "ready",
            "updated_at": now_iso(),
        }})

        # Characters
        characters = []
        for ch in plan.get("characters", []):
            doc = {
                "id": new_id(),
                "manga_id": manga_id,
                "name": ch.get("name", "İsimsiz"),
                "role": ch.get("role", "supporting"),
                "age": ch.get("age", ""),
                "appearance": ch.get("appearance", ""),
                "personality": ch.get("personality", ""),
                "backstory": ch.get("backstory", ""),
                "reference_image_url": None,
                "user_uploaded_reference": False,
                "created_at": now_iso(),
            }
            await db.characters.insert_one(doc)
            characters.append(doc)

        # Chapters
        for c in plan.get("chapters", [])[: body_dict["chapter_count"]]:
            await db.chapters.insert_one({
                "id": new_id(),
                "manga_id": manga_id,
                "number": c.get("number", 1),
                "title": c.get("title", "İsimsiz Bölüm"),
                "summary": c.get("summary", ""),
                "status": "outline",
                "scenes_count": 0,
                "created_at": now_iso(),
            })

        # Story memory
        await db.story_memory.insert_one({
            "id": new_id(),
            "manga_id": manga_id,
            "facts": [
                f"Setting: {plan.get('world', {}).get('setting', '')}",
                f"Power system: {plan.get('world', {}).get('power_system', 'None')}",
                f"Themes: {', '.join(plan.get('themes', []))}",
            ] + [f"{c['name']}: {c['appearance'][:80]}" for c in characters],
            "created_at": now_iso(),
        })

        await update(100, "done")
    except Exception as e:
        logger.error(f"Plan job failed: {e}")
        friendly = _sanitize_ai_error(e)
        await db.mangas.update_one({"id": manga_id}, {"$set": {"plan_status": "error"}})
        await update(0, "error", friendly)


# In-memory task registry to prevent GC of asyncio tasks
_background_tasks: set = set()


def _spawn(coro):
    t = asyncio.create_task(coro)
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return t


@api.post("/mangas")
async def create_manga(body: CreateMangaIn):
    manga_id = new_id()
    job_id = new_id()

    # Create shell manga immediately so it appears in library with a status
    shell = {
        "id": manga_id,
        "client_id": body.client_id,
        "title": "Hikâye örülüyor...",
        "logline": "",
        "synopsis": "",
        "world": {},
        "themes": [],
        "genre": body.genre,
        "art_style": body.art_style,
        "creativity": body.creativity,
        "chapter_count": body.chapter_count,
        "is_published": False,
        "published_at": None,
        "cover_url": None,
        "plan_status": "planning",
        "plan_job_id": job_id,
        "max_panels_per_chapter": DEFAULT_PANEL_CAP,
        "stats": {"text_calls": 0, "image_calls": 0, "panels_generated": 0, "chapters_generated": 0},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.mangas.insert_one(shell)

    await db.generation_jobs.insert_one({
        "id": job_id,
        "type": "plan",
        "target_id": manga_id,
        "manga_id": manga_id,
        "status": "queued",
        "progress": 0,
        "error": None,
        "retry_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })

    _spawn(_run_plan_generation(job_id, manga_id, body.model_dump()))
    return {"manga_id": manga_id, "job_id": job_id}


def _clean(doc: dict) -> dict:
    d = dict(doc)
    d.pop("_id", None)
    return d


@api.get("/mangas")
async def list_mangas(client_id: str = Query(...), published: Optional[bool] = None):
    query = {"client_id": client_id}
    if published is not None:
        query["is_published"] = published
    docs = await db.mangas.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"mangas": docs}


@api.get("/mangas/explore")
async def explore_mangas():
    docs = await db.mangas.find({"is_published": True}, {"_id": 0}).sort("published_at", -1).to_list(100)
    return {"mangas": docs}


@api.get("/mangas/{manga_id}")
async def get_manga(manga_id: str):
    manga = await db.mangas.find_one({"id": manga_id}, {"_id": 0})
    if not manga:
        raise HTTPException(404, "Manga bulunamadı")
    characters = await db.characters.find({"manga_id": manga_id}, {"_id": 0}).to_list(50)
    chapters = await db.chapters.find({"manga_id": manga_id}, {"_id": 0}).sort("number", 1).to_list(200)
    return {"manga": manga, "characters": characters, "chapters": chapters}


@api.patch("/mangas/{manga_id}/rename")
async def rename_manga(manga_id: str, body: RenameIn):
    res = await db.mangas.update_one({"id": manga_id}, {"$set": {"title": body.title, "updated_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(404, "Manga bulunamadı")
    return {"ok": True}


@api.post("/mangas/{manga_id}/publish")
async def publish_manga(manga_id: str, body: PublishIn):
    upd = {"is_published": body.is_published, "updated_at": now_iso()}
    upd["published_at"] = now_iso() if body.is_published else None
    res = await db.mangas.update_one({"id": manga_id}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(404, "Manga bulunamadı")
    return {"ok": True}


@api.delete("/mangas/{manga_id}")
async def delete_manga(manga_id: str):
    res = await db.mangas.delete_one({"id": manga_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Manga bulunamadı")
    await db.characters.delete_many({"manga_id": manga_id})
    await db.chapters.delete_many({"manga_id": manga_id})
    await db.scenes.delete_many({"manga_id": manga_id})
    await db.panels.delete_many({"manga_id": manga_id})
    await db.story_memory.delete_many({"manga_id": manga_id})
    await db.generation_jobs.delete_many({"manga_id": manga_id})
    return {"ok": True}


# ---------------- Characters ----------------
async def _run_portrait_generation(job_id: str, character_id: str):
    """Background worker: karakter portresi üret + kaydet."""
    async def update(progress: int, status: str = "running", error: Optional[str] = None):
        patch = {"progress": progress, "status": status, "updated_at": now_iso()}
        if error:
            patch["error"] = error
        await db.generation_jobs.update_one({"id": job_id}, {"$set": patch})

    try:
        char = await db.characters.find_one({"id": character_id}, {"_id": 0})
        if not char:
            await update(0, "error", "Karakter bulunamadı")
            return
        manga = await db.mangas.find_one({"id": char["manga_id"]}, {"_id": 0})
        if not manga:
            await update(0, "error", "Bağlı manga bulunamadı")
            return
        await update(10)

        prompt = CHARACTER_PORTRAIT_PROMPT.format(
            art_style=manga.get("art_style", "Manga-inspired"),
            name=char["name"],
            appearance=char["appearance"],
            personality=char["personality"],
        )
        img_bytes = await generate_image(prompt, session_id=f"portrait-{character_id}")
        await _bump_stats(char["manga_id"], image_calls=1)
        await update(85)

        storage_path = await asyncio.to_thread(upload_image, img_bytes, f"portraits/{char['manga_id']}", "png")
        url = f"/api/files/{storage_path}"
        await db.characters.update_one(
            {"id": character_id},
            {"$set": {"reference_image_url": url, "user_uploaded_reference": False}},
        )
        await update(100, "done")
    except Exception as e:
        logger.error(f"Portrait job failed: {e}")
        await update(0, "error", _sanitize_ai_error(e))


@api.post("/characters/{character_id}/generate-portrait")
async def generate_portrait(character_id: str):
    char = await db.characters.find_one({"id": character_id}, {"_id": 0})
    if not char:
        raise HTTPException(404, "Karakter bulunamadı")

    job_id = new_id()
    await db.generation_jobs.insert_one({
        "id": job_id,
        "type": "portrait",
        "target_id": character_id,
        "manga_id": char["manga_id"],
        "status": "queued",
        "progress": 0,
        "error": None,
        "retry_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    _spawn(_run_portrait_generation(job_id, character_id))
    return {"job_id": job_id}


@api.post("/characters/{character_id}/upload-reference")
async def upload_reference(character_id: str, file: UploadFile = File(...)):
    char = await db.characters.find_one({"id": character_id})
    if not char:
        raise HTTPException(404, "Karakter bulunamadı")
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png").lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        raise HTTPException(400, "Desteklenmeyen görsel türü")
    data = await file.read()
    storage_path = await asyncio.to_thread(upload_image, data, f"portraits/{char['manga_id']}", ext)
    url = f"/api/files/{storage_path}"
    await db.characters.update_one(
        {"id": character_id},
        {"$set": {"reference_image_url": url, "user_uploaded_reference": True}},
    )
    return {"reference_image_url": url}


# ---------------- Chapter generation ----------------
async def _run_chapter_generation(job_id: str, manga_id: str, chapter_id: str):
    """Background worker generating scenes → panels → images for a chapter."""
    async def update(progress: int, status: str = "running", error: Optional[str] = None):
        patch = {"progress": progress, "status": status, "updated_at": now_iso()}
        if error:
            patch["error"] = error
        await db.generation_jobs.update_one({"id": job_id}, {"$set": patch})

    try:
        await update(2, "running")
        manga = await db.mangas.find_one({"id": manga_id}, {"_id": 0})
        chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
        characters = await db.characters.find({"manga_id": manga_id}, {"_id": 0}).to_list(50)
        memory_doc = await db.story_memory.find_one({"manga_id": manga_id}, {"_id": 0})

        char_map = {c["name"]: c for c in characters}
        char_list_str = "; ".join([f"{c['name']} ({c['role']}): {c['appearance'][:80]}" for c in characters])
        memory_facts = "\n".join(memory_doc.get("facts", [])) if memory_doc else ""

        await db.chapters.update_one({"id": chapter_id}, {"$set": {"status": "generating"}})
        await update(10)

        # Scene decomposition
        scene_data = await generate_json(
            SCENE_DECOMP_SYSTEM,
            SCENE_DECOMP_USER.format(
                title=manga.get("title", ""),
                world_summary=json.dumps(manga.get("world", {})),
                story_memory=memory_facts,
                chapter_number=chapter.get("number", 0),
                chapter_title=chapter.get("title", ""),
                chapter_summary=chapter.get("summary", ""),
                characters=char_list_str,
            ),
            session_id=f"scenes-{chapter_id}",
        )
        await _bump_stats(manga_id, text_calls=1)
        scenes = scene_data.get("scenes", [])
        # Enforce per-manga panel cap
        cap = int(manga.get("max_panels_per_chapter", DEFAULT_PANEL_CAP))
        remaining = cap
        capped_scenes = []
        for s in scenes:
            if remaining <= 0:
                break
            panels = (s.get("panels") or [])[:remaining]
            if not panels:
                continue
            capped = dict(s)
            capped["panels"] = panels
            capped_scenes.append(capped)
            remaining -= len(panels)
        scenes = capped_scenes
        await update(25)

        # Persist scenes + panels; then generate images sequentially
        panels_to_gen = []
        for s in scenes:
            scene_id = new_id()
            await db.scenes.insert_one({
                "id": scene_id,
                "manga_id": manga_id,
                "chapter_id": chapter_id,
                "order": s.get("order", 0),
                "location": s.get("location", ""),
                "time_of_day": s.get("time_of_day", ""),
                "action_summary": s.get("action_summary", ""),
                "characters_present": s.get("characters_present", []),
                "created_at": now_iso(),
            })
            for p in s.get("panels", []):
                panel_id = new_id()
                panel_doc = {
                    "id": panel_id,
                    "manga_id": manga_id,
                    "chapter_id": chapter_id,
                    "scene_id": scene_id,
                    "scene_order": s.get("order", 0),
                    "order": p.get("order", 0),
                    "camera": p.get("camera", "medium"),
                    "description": p.get("description", ""),
                    "characters_in_panel": p.get("characters_in_panel", []),
                    "expression_and_pose": p.get("expression_and_pose", ""),
                    "background": p.get("background", ""),
                    "dialogue": p.get("dialogue", []),
                    "bubbles": [],
                    "image_url": None,
                    "status": "pending",
                    "created_at": now_iso(),
                }
                await db.panels.insert_one(panel_doc)
                panels_to_gen.append(panel_doc)

        total_panels = len(panels_to_gen)
        if total_panels == 0:
            await db.chapters.update_one({"id": chapter_id}, {"$set": {"status": "ready", "scenes_count": len(scenes)}})
            await update(100, "done")
            return

        # Load reference image bytes per character (once)
        ref_cache = {}
        for name, ch in char_map.items():
            if ch.get("reference_image_url"):
                path = ch["reference_image_url"].replace("/api/files/", "")
                try:
                    data, _ = await asyncio.to_thread(get_object, path)
                    ref_cache[name] = data
                except Exception as e:
                    logger.warning(f"Could not load ref for {name}: {e}")

        for i, panel in enumerate(panels_to_gen):
            try:
                chars_in = panel.get("characters_in_panel", [])
                refs = [ref_cache[n] for n in chars_in if n in ref_cache][:3]
                chars_desc = "; ".join([f"{n}: {char_map.get(n, {}).get('appearance', '')[:100]}" for n in chars_in]) or "None"
                prompt = IMAGE_PROMPT_TEMPLATE.format(
                    art_style=manga.get("art_style", "Manga-inspired"),
                    panel_description=panel["description"],
                    camera=panel["camera"],
                    characters_desc=chars_desc,
                    expression_and_pose=panel["expression_and_pose"],
                    background=panel["background"],
                )
                img_bytes = await generate_image(prompt, session_id=f"panel-{panel['id']}", reference_images=refs)
                await _bump_stats(manga_id, image_calls=1, panels=1)
                storage_path = await asyncio.to_thread(upload_image, img_bytes, f"panels/{manga_id}/{chapter_id}", "png")
                url = f"/api/files/{storage_path}"

                # Compute initial SVG bubble positions from dialogue
                bubbles = []
                dlg = panel.get("dialogue", [])
                for j, d in enumerate(dlg):
                    bubbles.append({
                        "id": new_id(),
                        "text": d.get("text", ""),
                        "type": d.get("type", "speech"),
                        "character": d.get("character", ""),
                        "x": 0.1 + (j % 2) * 0.55,
                        "y": 0.1 + (j // 2) * 0.25,
                        "width": 0.35,
                        "height": 0.15,
                    })
                await db.panels.update_one(
                    {"id": panel["id"]},
                    {"$set": {"image_url": url, "bubbles": bubbles, "status": "ready"}},
                )
            except Exception as e:
                logger.error(f"Panel {panel['id']} generation failed: {e}")
                await db.panels.update_one({"id": panel["id"]}, {"$set": {"status": "error", "error": str(e)}})

            progress = 25 + int(70 * (i + 1) / total_panels)
            await update(progress)

        # First panel becomes cover if not set
        first_panel = await db.panels.find_one({"manga_id": manga_id, "status": "ready", "image_url": {"$ne": None}}, {"_id": 0})
        if first_panel:
            m = await db.mangas.find_one({"id": manga_id}, {"_id": 0})
            if not m.get("cover_url"):
                await db.mangas.update_one({"id": manga_id}, {"$set": {"cover_url": first_panel["image_url"]}})

        await db.chapters.update_one({"id": chapter_id}, {"$set": {"status": "ready", "scenes_count": len(scenes)}})
        await _bump_stats(manga_id, chapters=1)
        await update(100, "done")

    except Exception as e:
        logger.error(f"Chapter job failed: {e}")
        await db.chapters.update_one({"id": chapter_id}, {"$set": {"status": "error"}})
        await update(0, "error", _sanitize_ai_error(e))


@api.post("/chapters/{chapter_id}/generate")
async def generate_chapter(chapter_id: str):
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(404, "Bölüm bulunamadı")
    # Delete previous scenes/panels for retry
    await db.scenes.delete_many({"chapter_id": chapter_id})
    await db.panels.delete_many({"chapter_id": chapter_id})

    job_id = new_id()
    await db.generation_jobs.insert_one({
        "id": job_id,
        "type": "chapter",
        "target_id": chapter_id,
        "manga_id": chapter["manga_id"],
        "status": "queued",
        "progress": 0,
        "error": None,
        "retry_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    _spawn(_run_chapter_generation(job_id, chapter["manga_id"], chapter_id))
    return {"job_id": job_id}


# ---------------- Batch chapter generation ----------------
async def _run_batch_chapters(batch_id: str, manga_id: str, jobs: list):
    """Sequentially run multiple chapter generation jobs."""
    total = len(jobs)
    failed = 0
    errors = []
    for idx, item in enumerate(jobs):
        chapter_id = item["chapter_id"]
        job_id = item["job_id"]
        try:
            await _run_chapter_generation(job_id, manga_id, chapter_id)
        except Exception as e:
            logger.error(f"Batch item failed {chapter_id}: {e}")
        # Inspect child job outcome
        child = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0, "status": 1, "error": 1})
        if child and child.get("status") == "error":
            failed += 1
            if child.get("error"):
                errors.append(child["error"])
        await db.generation_jobs.update_one(
            {"id": batch_id},
            {"$set": {"progress": int(100 * (idx + 1) / total), "updated_at": now_iso()}},
        )
    final_status = "done" if failed == 0 else ("error" if failed == total else "partial")
    await db.generation_jobs.update_one(
        {"id": batch_id},
        {"$set": {
            "status": final_status,
            "progress": 100,
            "failed_count": failed,
            "total_count": total,
            "error": errors[0] if errors else None,
            "updated_at": now_iso(),
        }},
    )


@api.post("/mangas/{manga_id}/chapters/batch-generate")
async def batch_generate(manga_id: str, body: BatchGenerateIn):
    manga = await db.mangas.find_one({"id": manga_id}, {"_id": 0})
    if not manga:
        raise HTTPException(404, "Manga bulunamadı")

    chapters = await db.chapters.find({"id": {"$in": body.chapter_ids}, "manga_id": manga_id}, {"_id": 0}).to_list(len(body.chapter_ids))
    if not chapters:
        raise HTTPException(404, "Eşleşen bölüm yok")

    # Order by chapter number
    chapters.sort(key=lambda c: c["number"])

    jobs = []
    for ch in chapters:
        # Reset scenes/panels for regen
        await db.scenes.delete_many({"chapter_id": ch["id"]})
        await db.panels.delete_many({"chapter_id": ch["id"]})
        job_id = new_id()
        await db.generation_jobs.insert_one({
            "id": job_id,
            "type": "chapter",
            "target_id": ch["id"],
            "manga_id": manga_id,
            "status": "queued",
            "progress": 0,
            "error": None,
            "retry_count": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        jobs.append({"chapter_id": ch["id"], "job_id": job_id, "chapter_number": ch["number"]})

    batch_id = new_id()
    await db.generation_jobs.insert_one({
        "id": batch_id,
        "type": "batch",
        "target_id": manga_id,
        "manga_id": manga_id,
        "status": "running",
        "progress": 0,
        "child_jobs": [j["job_id"] for j in jobs],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    _spawn(_run_batch_chapters(batch_id, manga_id, jobs))
    return {"batch_id": batch_id, "jobs": jobs}


# ---------------- Panel cap setting ----------------
@api.patch("/mangas/{manga_id}/panel-cap")
async def set_panel_cap(manga_id: str, body: PanelCapIn):
    res = await db.mangas.update_one(
        {"id": manga_id},
        {"$set": {"max_panels_per_chapter": body.max_panels_per_chapter, "updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Manga bulunamadı")
    return {"ok": True, "max_panels_per_chapter": body.max_panels_per_chapter}


# ---------------- Usage summary ----------------
@api.get("/usage/summary")
async def usage_summary(client_id: str = Query(...)):
    """Aggregate usage stats across a client's mangas."""
    mangas = await db.mangas.find({"client_id": client_id}, {"_id": 0, "stats": 1, "id": 1, "title": 1}).to_list(500)
    total = {"text_calls": 0, "image_calls": 0, "panels_generated": 0, "chapters_generated": 0, "mangas": len(mangas)}
    for m in mangas:
        s = m.get("stats") or {}
        for k in ("text_calls", "image_calls", "panels_generated", "chapters_generated"):
            total[k] += int(s.get(k, 0) or 0)
    # Ücretsiz katmandayız (Google Gemini free + Pollinations.ai) - kredi 0
    est_credits = 0.0
    return {"totals": total, "estimated_credits_spent_usd": est_credits}


# ---------------- PDF Export ----------------
def _draw_bubble_on_image(img: Image.Image, bubble: dict):
    """Bake a single dialogue bubble onto the PIL image."""
    W, H = img.size
    x = max(0, int(bubble.get("x", 0) * W))
    y = max(0, int(bubble.get("y", 0) * H))
    w = max(40, int(bubble.get("width", 0.3) * W))
    h = max(30, int(bubble.get("height", 0.15) * H))
    text = bubble.get("text", "") or ""
    btype = bubble.get("type", "speech")

    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font_size = max(12, int(min(W, H) * 0.022))
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    if btype == "sfx":
        # Big yellow outlined SFX text, no bubble
        stroke = max(2, font_size // 6)
        draw.text((x, y), text.upper(), fill=(255, 220, 0, 255), font=font, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        return

    # Bubble background + border
    box = (x, y, x + w, y + h)
    if btype == "thought":
        draw.ellipse(box, fill=(255, 255, 255, 235), outline=(20, 20, 20, 255), width=3)
    elif btype == "shout":
        # jagged look via double rectangle
        draw.rectangle(box, fill=(255, 255, 255, 240), outline=(20, 20, 20, 255), width=4)
        draw.rectangle((x + 3, y + 3, x + w - 3, y + h - 3), outline=(20, 20, 20, 255), width=1)
    elif btype == "narration":
        draw.rectangle(box, fill=(253, 246, 227, 240), outline=(70, 60, 30, 255), width=2)
    elif btype == "whisper":
        for dx in range(0, w, 8):
            draw.line((x + dx, y, x + dx + 4, y), fill=(30, 30, 30, 255), width=2)
            draw.line((x + dx, y + h, x + dx + 4, y + h), fill=(30, 30, 30, 255), width=2)
        for dy in range(0, h, 8):
            draw.line((x, y + dy, x, y + dy + 4), fill=(30, 30, 30, 255), width=2)
            draw.line((x + w, y + dy, x + w, y + dy + 4), fill=(30, 30, 30, 255), width=2)
        draw.rectangle((x + 2, y + 2, x + w - 2, y + h - 2), fill=(255, 255, 255, 220))
    else:  # speech
        draw.rounded_rectangle(box, radius=max(10, h // 4), fill=(255, 255, 255, 240), outline=(20, 20, 20, 255), width=3)

    # Word-wrap text within bubble
    pad = 8
    max_w = w - pad * 2
    words = text.split()
    lines = []
    cur = ""
    for word in words:
        trial = (cur + " " + word).strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] > max_w and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)

    line_h = font.getbbox("Ag")[3] + 2
    total_h = line_h * len(lines)
    ty = y + max(pad, (h - total_h) // 2)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        tx = x + (w - tw) // 2
        draw.text((tx, ty), line, fill=(10, 10, 10, 255), font=font)
        ty += line_h


def _build_chapter_pdf_sync(panel_docs: list, images_bytes: list, chapter_title: str) -> bytes:
    """Composite bubbles onto each panel image and export as multi-page PDF."""
    rendered = []
    for panel, img_data in zip(panel_docs, images_bytes):
        img = Image.open(io.BytesIO(img_data)).convert("RGB")
        for b in panel.get("bubbles", []) or []:
            _draw_bubble_on_image(img, b)
        rendered.append(img)

    if not rendered:
        # Empty placeholder
        blank = Image.new("RGB", (800, 1000), (12, 12, 20))
        d = ImageDraw.Draw(blank)
        d.text((40, 40), f"No panels ready\n{chapter_title}", fill=(240, 240, 240))
        rendered.append(blank)

    buf = io.BytesIO()
    first = rendered[0]
    rest = rendered[1:]
    first.save(buf, format="PDF", save_all=True, append_images=rest, resolution=150.0)
    return buf.getvalue()


@api.get("/chapters/{chapter_id}/export/pdf")
async def export_chapter_pdf(chapter_id: str):
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(404, "Bölüm bulunamadı")
    panels = await db.panels.find(
        {"chapter_id": chapter_id, "status": "ready", "image_url": {"$ne": None}},
        {"_id": 0},
    ).sort([("scene_order", 1), ("order", 1)]).to_list(500)

    if not panels:
        raise HTTPException(400, "Bu bölümde dışa aktarılacak hazır panel yok")

    async def fetch(p):
        try:
            path = p["image_url"].replace("/api/files/", "")
            data, _ = await asyncio.to_thread(get_object, path)
            return data
        except Exception as e:
            logger.warning(f"Skipping panel {p.get('id')} in PDF export: {e}")
            return None

    images_bytes = await asyncio.gather(*(fetch(p) for p in panels))
    # Filter out failed panels while keeping alignment
    valid_pairs = [(p, b) for p, b in zip(panels, images_bytes) if b]
    if not valid_pairs:
        raise HTTPException(502, "Tüm panel görselleri kullanılamıyor")

    panels_ok = [p for p, _ in valid_pairs]
    bytes_ok = [b for _, b in valid_pairs]
    pdf_bytes = await asyncio.to_thread(_build_chapter_pdf_sync, panels_ok, bytes_ok, chapter.get("title", "chapter"))

    number = int(chapter.get("number", 0) or 0)
    title_raw = chapter.get("title") or "chapter"
    # ASCII-safe filename fallback + RFC 5987 encoded filename*
    ascii_title = re.sub(r"[^A-Za-z0-9_.-]", "_", title_raw)[:40] or "chapter"
    ascii_name = f"chapter-{number:02d}-{ascii_title}.pdf"
    utf8_name = f"chapter-{number:02d}-{title_raw}.pdf".replace("\\", "_").replace("/", "_")
    encoded = urlquote(utf8_name, safe="")
    cd = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": cd},
    )


@api.get("/jobs/{job_id}")
async def get_job(job_id: str):
    doc = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "İş bulunamadı")
    return doc


@api.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    async def event_gen():
        last_progress = -1
        # ~15 min max
        for _ in range(1125):
            doc = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
            if not doc:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                return
            if doc["progress"] != last_progress or doc["status"] in ("done", "error"):
                last_progress = doc["progress"]
                yield f"data: {json.dumps({'progress': doc['progress'], 'status': doc['status'], 'error': doc.get('error')})}\n\n"
            if doc["status"] in ("done", "error"):
                return
            await asyncio.sleep(0.8)
        yield f"data: {json.dumps({'status': 'timeout'})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- Reader ----------------
@api.get("/chapters/{chapter_id}/panels")
async def chapter_panels(chapter_id: str):
    panels = await db.panels.find({"chapter_id": chapter_id}, {"_id": 0}).sort([("scene_order", 1), ("order", 1)]).to_list(500)
    return {"panels": panels}


@api.patch("/panels/{panel_id}/bubbles")
async def update_bubbles(panel_id: str, body: BubbleIn):
    bubbles_dump = [b.model_dump() for b in body.bubbles]
    res = await db.panels.update_one({"id": panel_id}, {"$set": {"bubbles": bubbles_dump}})
    if res.matched_count == 0:
        raise HTTPException(404, "Panel bulunamadı")
    return {"ok": True}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
