"""Migration tests: Emergent LLM/Object-Storage -> Google Gemini (text) + Pollinations.ai (images)
+ local filesystem storage.

Expected state: GOOGLE_API_KEY is EMPTY in /app/backend/.env, so every text path must fail with the
Turkish sanitized message, while image-only paths (Pollinations) must still work.
"""
import io
import os
import re
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL is missing from env and /app/frontend/.env")
API = base_url.rstrip("/") + "/api"

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or backend_env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or backend_env.get("DB_NAME")
STORAGE_ROOT = Path(backend_env.get("STORAGE_ROOT") or "/app/backend/uploads")
GOOGLE_KEY_EMPTY = not (backend_env.get("GOOGLE_API_KEY") or "").strip()

TAG = "TEST_mig_" + uuid.uuid4().hex[:8]
KEY_ERR = "Google API anahtarı ayarlanmamış"

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000154a24f5f0000000049454e44ae42"
    "6082"
)


def nid():
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def mdb():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    yield s
    s.close()


@pytest.fixture(scope="module", autouse=True)
def cleanup(mdb):
    yield
    ids = [m["id"] for m in mdb.mangas.find({"client_id": {"$regex": f"^{TAG}"}}, {"id": 1})]
    for col in ("chapters", "panels", "scenes", "characters", "generation_jobs"):
        mdb[col].delete_many({"manga_id": {"$in": ids}})
    mdb.generation_jobs.delete_many({"manga_id": {"$in": ids}})
    mdb.mangas.delete_many({"client_id": {"$regex": f"^{TAG}"}})


def wait_job(http, job_id, timeout=150):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = http.get(f"{API}/jobs/{job_id}", timeout=30)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("done", "error"):
            return last
        time.sleep(2)
    return last


# ---------------- Module: static code assertions (no emergentintegrations) ----------------
class TestNoEmergentIntegrations:
    def test_backend_py_files_have_no_emergentintegrations(self):
        hits = []
        for p in Path("/app/backend").glob("*.py"):
            txt = p.read_text(encoding="utf-8")
            if "emergentintegrations" in txt or "integrations.emergentagent.com" in txt:
                hits.append(p.name)
        assert hits == [], f"Emergent integration references still present: {hits}"

    def test_ai_service_uses_google_genai(self):
        txt = Path("/app/backend/ai_service.py").read_text(encoding="utf-8")
        assert "import google.generativeai" in txt
        assert "pollinations" in txt.lower()
        for banned in ("LlmChat", "UserMessage", "ImageContent", "EMERGENT_LLM_KEY"):
            assert banned not in txt, f"{banned} still referenced in ai_service.py"

    def test_storage_service_is_local_only(self):
        txt = Path("/app/backend/storage_service.py").read_text(encoding="utf-8")
        assert "emergentagent.com" not in txt
        for banned in ("requests.", "httpx", "aiohttp"):
            assert banned not in txt, f"storage_service.py still makes HTTP calls via {banned}"
        assert "STORAGE_ROOT" in txt

    def test_server_no_emergent_key(self):
        txt = Path("/app/backend/server.py").read_text(encoding="utf-8")
        assert "EMERGENT_LLM_KEY" not in txt
        assert KEY_ERR in txt


# ---------------- Module: health ----------------
class TestHealthMigration:
    def test_health(self, http):
        r = http.get(f"{API}/health", timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True


# ---------------- Module: local filesystem storage ----------------
class TestLocalStorage:
    def test_upload_then_disk_then_download(self, http):
        r = http.post(
            f"{API}/upload/character-reference",
            files={"file": ("ref.png", PNG_1x1, "image/png")},
            data={"client_id": f"{TAG}-store"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        sp = body["storage_path"]
        assert sp.startswith("ai-manga-studio/user-refs/"), sp
        assert body["url"] == f"/api/files/{sp}"

        # physically on disk
        on_disk = STORAGE_ROOT / sp
        assert on_disk.exists(), f"file missing on disk: {on_disk}"
        assert on_disk.read_bytes() == PNG_1x1

        # served back identically
        g = http.get(f"{API}/files/{sp}", timeout=60)
        assert g.status_code == 200, g.text
        assert g.content == PNG_1x1
        assert g.headers["content-type"].startswith("image/png")

    def test_file_404(self, http):
        r = http.get(f"{API}/files/ai-manga-studio/user-refs/nope-{nid()}.png", timeout=60)
        assert r.status_code == 404, r.text
        assert "Bulunamadı" in r.json().get("detail", "")

    @pytest.mark.parametrize(
        "evil",
        [
            "../../etc/passwd",
            "..%2f..%2f..%2fetc%2fpasswd",
            "ai-manga-studio/../../../etc/passwd",
        ],
    )
    def test_path_traversal_blocked(self, http, evil):
        """Ingress/urllib normalise dot-segments, so status may be 200 (SPA html) / 400;
        the security assertion is that no system file content is ever returned."""
        r = http.get(f"{API}/files/{evil}", timeout=60)
        assert "root:" not in r.text, "system file leaked!"
        assert "/bin/bash" not in r.text, "system file leaked!"

    def test_path_traversal_blocked_at_backend(self):
        """Hit the backend directly with un-normalised path to exercise _safe_path."""
        import subprocess

        out = subprocess.run(
            ["curl", "-s", "-w", "\n%{http_code}", "--path-as-is",
             "http://localhost:8001/api/files/../../../etc/passwd"],
            capture_output=True, text=True, timeout=60,
        ).stdout
        body, _, code = out.rpartition("\n")
        assert code.strip() == "404", out
        assert "root:" not in body

    def test_unsupported_extension_rejected(self, http):
        r = http.post(
            f"{API}/upload/character-reference",
            files={"file": ("evil.svg", b"<svg/>", "image/svg+xml")},
            data={"client_id": f"{TAG}-store"},
            timeout=60,
        )
        assert r.status_code == 400, r.text


# ---------------- Module: manga creation + plan job (text path -> expected sanitized error) ----------------
class TestPlanJobSanitizedError:
    def test_create_manga_is_fast_and_async(self, http):
        t0 = time.time()
        r = http.post(
            f"{API}/mangas",
            json={
                "idea": "Karanlik bir zamanda kayip bir samuray",
                "client_id": f"{TAG}-plan",
                "chapter_count": 2,
            },
            timeout=60,
        )
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("manga_id") and body.get("job_id")
        assert elapsed < 3.0, f"create_manga took {elapsed:.2f}s (should be immediate/async)"

        job = wait_job(http, body["job_id"])
        assert job is not None
        assert job["status"] == "error", job
        assert KEY_ERR in (job.get("error") or ""), job.get("error")

        m = http.get(f"{API}/mangas/{body['manga_id']}", timeout=30)
        assert m.status_code == 200, m.text
        assert m.json()["manga"]["plan_status"] == "error"

    @pytest.mark.parametrize("cc,expected", [(0, 422), (21, 422), (1, 200), (20, 200)])
    def test_chapter_count_validation(self, http, cc, expected):
        r = http.post(
            f"{API}/mangas",
            json={
                "idea": "Karanlik bir zamanda kayip bir samuray",
                "client_id": f"{TAG}-val",
                "chapter_count": cc,
            },
            timeout=60,
        )
        assert r.status_code == expected, r.text


# ---------------- Module: Pollinations image path (must work without GOOGLE_API_KEY) ----------------
class TestPollinationsPortrait:
    def test_generate_portrait_uses_pollinations(self, http, mdb):
        manga_id = nid()
        char_id = nid()
        mdb.mangas.insert_one(
            {
                "id": manga_id,
                "client_id": f"{TAG}-poll",
                "title": "TEST migration poll",
                "art_style": "Manga-inspired",
                "plan_status": "done",
                "stats": {},
            }
        )
        mdb.characters.insert_one(
            {
                "id": char_id,
                "manga_id": manga_id,
                "name": "Kenji",
                "appearance": "young male samurai, short black hair, scar on cheek, worn grey kimono",
                "personality": "stoic and loyal",
            }
        )

        # iter7: endpoint is now job-based -> returns {job_id}, poll /api/jobs/{id}
        r = http.post(f"{API}/characters/{char_id}/generate-portrait", timeout=60)
        assert r.status_code == 200, f"portrait enqueue failed: {r.status_code} {r.text[:400]}"
        job_id = r.json()["job_id"]

        deadline = time.time() + 240
        job = None
        while time.time() < deadline:
            jr = http.get(f"{API}/jobs/{job_id}", timeout=30)
            assert jr.status_code == 200, jr.text[:300]
            job = jr.json()
            if job["status"] in ("done", "error"):
                break
            time.sleep(2)
        assert job and job["status"] == "done", f"portrait job not done: {job}"

        ch0 = mdb.characters.find_one({"id": char_id})
        url = ch0["reference_image_url"]
        assert url.startswith("/api/files/ai-manga-studio/portraits/"), url

        sp = url.replace("/api/files/", "")
        on_disk = STORAGE_ROOT / sp
        assert on_disk.exists(), f"portrait not on disk: {on_disk}"
        assert on_disk.stat().st_size > 5000, on_disk.stat().st_size

        g = http.get(f"{API}/files/{sp}", timeout=60)
        assert g.status_code == 200
        assert g.headers["content-type"].startswith("image/")

        ch = mdb.characters.find_one({"id": char_id})
        assert ch["reference_image_url"] == url
        assert ch["user_uploaded_reference"] is False


# ---------------- Module: chapter generation (text decomposition -> sanitized error) ----------------
class TestChapterGenerationError:
    def _seed(self, mdb, chapters=1):
        manga_id = nid()
        mdb.mangas.insert_one(
            {
                "id": manga_id,
                "client_id": f"{TAG}-chap",
                "title": "TEST migration chap",
                "art_style": "Manga-inspired",
                "genre": "Fantasy",
                "plan_status": "done",
                "premise": "kayip samuray",
                "world": "feodal japonya",
                "tone": "karanlik",
                "characters": [],
                "stats": {},
            }
        )
        ids = []
        for i in range(chapters):
            cid = nid()
            mdb.chapters.insert_one(
                {
                    "id": cid,
                    "manga_id": manga_id,
                    "number": i + 1,
                    "title": f"Bolum {i+1}",
                    "summary": "Samuray koye varir.",
                    "status": "pending",
                }
            )
            ids.append(cid)
        return manga_id, ids

    def test_single_chapter_generate_error(self, http, mdb):
        manga_id, (cid,) = self._seed(mdb, 1)
        r = http.post(f"{API}/chapters/{cid}/generate", timeout=60)
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]

        job = wait_job(http, job_id)
        assert job["status"] == "error", job
        assert KEY_ERR in (job.get("error") or ""), job.get("error")
        assert mdb.chapters.find_one({"id": cid})["status"] == "error"

    def test_batch_generate_all_children_error(self, http, mdb):
        manga_id, ids = self._seed(mdb, 2)
        r = http.post(
            f"{API}/mangas/{manga_id}/chapters/batch-generate",
            json={"chapter_ids": ids},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("batch_id")
        assert len(body.get("jobs", [])) == 2

        batch = wait_job(http, body["batch_id"], timeout=240)
        assert batch["status"] == "error", batch
        assert batch.get("failed_count") == 2
        assert batch.get("total_count") == 2
        for j in body["jobs"]:
            cj = http.get(f"{API}/jobs/{j['job_id']}", timeout=30).json()
            assert cj["status"] == "error", cj
            assert KEY_ERR in (cj.get("error") or ""), cj.get("error")


# ---------------- Module: PDF export using local storage ----------------
class TestPdfExportLocalStorage:
    def test_export_pdf(self, http, mdb):
        up = http.post(
            f"{API}/upload/character-reference",
            files={"file": ("panel.png", _real_png(), "image/png")},
            data={"client_id": f"{TAG}-pdf"},
            timeout=60,
        )
        assert up.status_code == 200, up.text
        img_url = up.json()["url"]

        manga_id, chapter_id, panel_id = nid(), nid(), nid()
        mdb.mangas.insert_one(
            {"id": manga_id, "client_id": f"{TAG}-pdf", "title": "TEST migration pdf", "stats": {}}
        )
        mdb.chapters.insert_one(
            {"id": chapter_id, "manga_id": manga_id, "number": 1, "title": "Bolum 1", "status": "ready"}
        )
        mdb.panels.insert_one(
            {
                "id": panel_id,
                "manga_id": manga_id,
                "chapter_id": chapter_id,
                "index": 1,
                "image_url": img_url,
                "status": "ready",
                "bubbles": [
                    {
                        "id": "b1",
                        "text": "Merhaba dünya",
                        "type": "speech",
                        "character": "Kenji",
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.4,
                        "height": 0.2,
                    }
                ],
            }
        )

        r = http.get(f"{API}/chapters/{chapter_id}/export/pdf", timeout=120)
        assert r.status_code == 200, r.text[:400]
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1000


def _real_png():
    from PIL import Image

    img = Image.new("RGB", (600, 800), (120, 140, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------- Module: env / config ----------------
class TestEnvState:
    def test_google_api_key_is_empty_as_expected(self):
        assert GOOGLE_KEY_EMPTY, "GOOGLE_API_KEY is set; migration error-path tests are not applicable"

    def test_storage_root_exists(self):
        assert STORAGE_ROOT.exists() and STORAGE_ROOT.is_dir()
