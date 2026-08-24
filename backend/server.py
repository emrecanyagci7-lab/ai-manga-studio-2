"""AI Manga Studio backend."""
import os
import uuid
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Header, Query
from fastapi.responses import StreamingResponse, Response
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from dotenv import load_dotenv

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


def _sanitize_ai_error(e: Exception) -> str:
    """Return a friendly error message and hide internal cost/budget details."""
    msg = str(e)
    low = msg.lower()
    if "budget" in low and "exceed" in low:
        return "AI service is temporarily unavailable (usage limit reached). Please try again later."
    if "rate limit" in low or "429" in low:
        return "AI service is busy. Please try again in a moment."
    if "timeout" in low:
        return "AI service timed out. Please try again."
    return "AI generation failed. Please try again."


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
            {"$set": {"status": "error", "error": "Interrupted by server restart", "updated_at": now_iso()}},
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
        raise HTTPException(status_code=404, detail="Not found")
    return Response(content=data, media_type=ct, headers={"Cache-Control": "public, max-age=86400"})


@api.post("/upload/character-reference")
async def upload_character_ref(file: UploadFile = File(...), client_id: str = Form(...)):
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png").lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        raise HTTPException(400, "Unsupported image type")
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
        await update(70, "running")

        # Fill in manga details
        await db.mangas.update_one({"id": manga_id}, {"$set": {
            "title": plan.get("title", "Untitled Manga"),
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
                "name": ch.get("name", "Unnamed"),
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
                "title": c.get("title", "Untitled Chapter"),
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
        "title": "Weaving story...",
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
        raise HTTPException(404, "Manga not found")
    characters = await db.characters.find({"manga_id": manga_id}, {"_id": 0}).to_list(50)
    chapters = await db.chapters.find({"manga_id": manga_id}, {"_id": 0}).sort("number", 1).to_list(200)
    return {"manga": manga, "characters": characters, "chapters": chapters}


@api.patch("/mangas/{manga_id}/rename")
async def rename_manga(manga_id: str, body: RenameIn):
    res = await db.mangas.update_one({"id": manga_id}, {"$set": {"title": body.title, "updated_at": now_iso()}})
    if res.matched_count == 0:
        raise HTTPException(404, "Manga not found")
    return {"ok": True}


@api.post("/mangas/{manga_id}/publish")
async def publish_manga(manga_id: str, body: PublishIn):
    upd = {"is_published": body.is_published, "updated_at": now_iso()}
    upd["published_at"] = now_iso() if body.is_published else None
    res = await db.mangas.update_one({"id": manga_id}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(404, "Manga not found")
    return {"ok": True}


@api.delete("/mangas/{manga_id}")
async def delete_manga(manga_id: str):
    res = await db.mangas.delete_one({"id": manga_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Manga not found")
    await db.characters.delete_many({"manga_id": manga_id})
    await db.chapters.delete_many({"manga_id": manga_id})
    await db.scenes.delete_many({"manga_id": manga_id})
    await db.panels.delete_many({"manga_id": manga_id})
    await db.story_memory.delete_many({"manga_id": manga_id})
    await db.generation_jobs.delete_many({"manga_id": manga_id})
    return {"ok": True}


# ---------------- Characters ----------------
@api.post("/characters/{character_id}/generate-portrait")
async def generate_portrait(character_id: str):
    char = await db.characters.find_one({"id": character_id}, {"_id": 0})
    if not char:
        raise HTTPException(404, "Character not found")
    manga = await db.mangas.find_one({"id": char["manga_id"]}, {"_id": 0})
    if not manga:
        raise HTTPException(404, "Parent manga not found")

    prompt = CHARACTER_PORTRAIT_PROMPT.format(
        art_style=manga.get("art_style", "Manga-inspired"),
        name=char["name"],
        appearance=char["appearance"],
        personality=char["personality"],
    )
    try:
        img_bytes = await generate_image(prompt, session_id=f"portrait-{character_id}")
    except Exception as e:
        logger.error(f"Portrait gen failed: {e}")
        raise HTTPException(503, _sanitize_ai_error(e))

    storage_path = await asyncio.to_thread(upload_image, img_bytes, f"portraits/{char['manga_id']}", "png")
    url = f"/api/files/{storage_path}"
    await db.characters.update_one(
        {"id": character_id},
        {"$set": {"reference_image_url": url, "user_uploaded_reference": False}},
    )
    return {"reference_image_url": url}


@api.post("/characters/{character_id}/upload-reference")
async def upload_reference(character_id: str, file: UploadFile = File(...)):
    char = await db.characters.find_one({"id": character_id})
    if not char:
        raise HTTPException(404, "Character not found")
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png").lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        raise HTTPException(400, "Unsupported image type")
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
                title=manga["title"],
                world_summary=json.dumps(manga.get("world", {})),
                story_memory=memory_facts,
                chapter_number=chapter["number"],
                chapter_title=chapter["title"],
                chapter_summary=chapter["summary"],
                characters=char_list_str,
            ),
            session_id=f"scenes-{chapter_id}",
        )
        scenes = scene_data.get("scenes", [])
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
        await update(100, "done")

    except Exception as e:
        logger.error(f"Chapter job failed: {e}")
        await db.chapters.update_one({"id": chapter_id}, {"$set": {"status": "error"}})
        await update(0, "error", _sanitize_ai_error(e))


@api.post("/chapters/{chapter_id}/generate")
async def generate_chapter(chapter_id: str):
    chapter = await db.chapters.find_one({"id": chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(404, "Chapter not found")
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


@api.get("/jobs/{job_id}")
async def get_job(job_id: str):
    doc = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job not found")
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
        raise HTTPException(404, "Panel not found")
    return {"ok": True}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
