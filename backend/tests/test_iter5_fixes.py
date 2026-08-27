"""Iteration-5 retest of the fixes reported in iteration_4.

1. CRITICAL: Pollinations 404 caused by newlines (%0A) in the multi-line prompt.
2. MINOR: _run_chapter_generation uses chapter.get(...) -> no KeyError masking.
3. MINOR: generate_json short-circuits when GOOGLE_API_KEY empty; md5-based stable seed.
"""
import asyncio
import hashlib
import os
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

TAG = "TEST_it5_" + uuid.uuid4().hex[:8]
KEY_ERR = "Google API anahtarı ayarlanmamış"


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
    for col in ("chapters", "panels", "scenes", "characters", "generation_jobs", "story_memory"):
        mdb[col].delete_many({"manga_id": {"$in": ids}})
    mdb.mangas.delete_many({"client_id": {"$regex": f"^{TAG}"}})


def wait_job(http, job_id, timeout=120):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = http.get(f"{API}/jobs/{job_id}", timeout=30)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("done", "error"):
            return last
        time.sleep(1.5)
    return last


def _seed_char(mdb, name="Kenji"):
    manga_id, char_id = nid(), nid()
    mdb.mangas.insert_one({
        "id": manga_id,
        "client_id": f"{TAG}-poll",
        "title": "TEST it5 poll",
        "art_style": "Manga-inspired",
        "plan_status": "done",
        "stats": {},
    })
    mdb.characters.insert_one({
        "id": char_id,
        "manga_id": manga_id,
        "name": name,
        "appearance": "young male samurai, short black hair, scar on left cheek, worn grey kimono",
        "personality": "stoic, loyal, quietly angry",
    })
    return manga_id, char_id


# ---------------- Fix 1: Pollinations multi-line prompt (CRITICAL) ----------------
class TestPollinationsMultilinePromptFix:
    def test_generate_portrait_returns_real_image(self, http, mdb):
        _, char_id = _seed_char(mdb)
        t0 = time.time()
        # iter7: job-based endpoint -> {job_id}
        r = http.post(f"{API}/characters/{char_id}/generate-portrait", timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        job = wait_job(http, r.json()["job_id"], timeout=240)
        elapsed = time.time() - t0
        assert job and job["status"] == "done", f"job not done: {job}"
        url = mdb.characters.find_one({"id": char_id})["reference_image_url"]
        assert url.startswith("/api/files/ai-manga-studio/portraits/"), url

        sp = url.replace("/api/files/", "")
        on_disk = STORAGE_ROOT / sp
        assert on_disk.exists(), f"missing on disk: {on_disk}"
        size = on_disk.stat().st_size
        assert size > 5000, f"image too small: {size}"
        head = on_disk.read_bytes()[:8]
        assert head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n", head.hex()
        print(f"portrait ok: {size} bytes in {elapsed:.1f}s")

        # served over API
        g = http.get(f"{API}/files/{sp}", timeout=60)
        assert g.status_code == 200
        assert g.headers["content-type"].startswith("image/")

        ch = mdb.characters.find_one({"id": char_id})
        assert ch["reference_image_url"] == url
        assert ch["user_uploaded_reference"] is False

    def test_raw_multiline_prompt_is_normalised_before_quoting(self):
        """Direct unit check of the fixed helper with the real multi-line app prompt."""
        import sys
        sys.path.insert(0, "/app/backend")
        import urllib.parse

        from ai_service import _fetch_pollinations_sync  # noqa: F401
        from prompts import CHARACTER_PORTRAIT_PROMPT

        prompt = CHARACTER_PORTRAIT_PROMPT.format(
            art_style="Manga-inspired", name="Kenji",
            appearance="short black hair, scar", personality="stoic",
        )
        assert "\n" in prompt, "prompt is no longer multi-line; test assumption stale"
        clean = " ".join(prompt.split())[:1500]
        assert "%0A" not in urllib.parse.quote(clean, safe="")

        # Pollinations rate-limits aggressively (429); retry a couple of times.
        last_err = None
        for _ in range(3):
            try:
                data = _fetch_pollinations_sync(prompt, 12345)
                assert len(data) > 5000, len(data)
                assert data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"
                return
            except Exception as e:
                last_err = e
                if "429" not in str(e):
                    raise
                time.sleep(20)
        pytest.skip(f"Pollinations rate-limited (429) during test run: {last_err}")


# ---------------- Fix 3: stable md5 seed ----------------
class TestStableSeed:
    def test_seed_is_md5_deterministic(self):
        import sys
        sys.path.insert(0, "/app/backend")
        import ai_service

        session_id = "portrait-abc123"
        expected = int(hashlib.md5(session_id.encode("utf-8")).hexdigest()[:8], 16) % (2 ** 31)

        seen = []

        def fake(prompt, seed):
            seen.append(seed)
            return b"x" * 2000

        orig = ai_service._fetch_pollinations_sync
        ai_service._fetch_pollinations_sync = fake
        try:
            asyncio.run(ai_service.generate_image("p", session_id=session_id))
            asyncio.run(ai_service.generate_image("p", session_id=session_id))
        finally:
            ai_service._fetch_pollinations_sync = orig

        assert seen == [expected, expected], (seen, expected)

    def test_repeat_portrait_same_character_deterministic(self, http, mdb):
        """Same character -> same session_id -> same seed. Pollinations output itself is NOT
        byte-deterministic (enhance=true rewrites the prompt server-side), so only assert both
        calls succeed and produce valid images; seed determinism is asserted in the unit test."""
        _, char_id = _seed_char(mdb, name="Aiko")
        blobs = []
        for _ in range(2):
            r = http.post(f"{API}/characters/{char_id}/generate-portrait", timeout=60)
            assert r.status_code == 200, r.text[:300]
            job = wait_job(http, r.json()["job_id"], timeout=240)
            assert job and job["status"] == "done", f"job not done: {job}"
            sp = mdb.characters.find_one({"id": char_id})["reference_image_url"].replace("/api/files/", "")
            blobs.append((STORAGE_ROOT / sp).read_bytes())
        for b in blobs:
            assert len(b) > 5000
            assert b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n"
        print(f"repeat portrait sizes: {[len(b) for b in blobs]}")


# ---------------- Fix 3b: generate_json fast-fail ----------------
class TestFastFailWithoutKey:
    def test_plan_job_fails_fast(self, http, mdb):
        r = http.post(f"{API}/mangas", json={
            "idea": "Kayip bir samurayin karanlik yolculugu",
            "client_id": f"{TAG}-fast",
            "chapter_count": 2,
        }, timeout=60)
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        t0 = time.time()
        job = wait_job(http, job_id, timeout=30)
        assert job["status"] == "error", job
        assert KEY_ERR in (job.get("error") or ""), job.get("error")
        # job created_at/updated_at based duration is more precise than poll loop
        doc = mdb.generation_jobs.find_one({"id": job_id}, {"_id": 0})
        print(f"job error after poll {time.time()-t0:.2f}s; doc={doc.get('created_at')} -> {doc.get('updated_at')}")

        from datetime import datetime
        d0 = datetime.fromisoformat(doc["created_at"].replace("Z", "+00:00"))
        d1 = datetime.fromisoformat(doc["updated_at"].replace("Z", "+00:00"))
        dur = (d1 - d0).total_seconds()
        assert dur < 2.0, f"plan job took {dur:.2f}s to fail (expected <2s fast-fail)"


# ---------------- Fix 2: chapter doc missing 'summary' ----------------
class TestChapterMissingSummary:
    def test_chapter_without_summary_field(self, http, mdb):
        manga_id, chapter_id = nid(), nid()
        mdb.mangas.insert_one({
            "id": manga_id, "client_id": f"{TAG}-nosum", "title": "TEST it5 nosum",
            "art_style": "Manga-inspired", "genre": "Fantasy", "plan_status": "done",
            "premise": "kayip samuray", "world": {"setting": "feodal japonya"},
            "tone": "karanlik", "characters": [], "stats": {},
        })
        # deliberately NO 'summary' and NO 'title'
        mdb.chapters.insert_one({
            "id": chapter_id, "manga_id": manga_id, "number": 1, "status": "pending",
        })
        r = http.post(f"{API}/chapters/{chapter_id}/generate", timeout=60)
        assert r.status_code == 200, r.text
        job = wait_job(http, r.json()["job_id"], timeout=60)
        assert job["status"] == "error", job
        err = job.get("error") or ""
        assert KEY_ERR in err, f"expected sanitized key error, got: {err!r}"
        assert "summary" not in err.lower(), f"KeyError leaked: {err!r}"
        assert mdb.chapters.find_one({"id": chapter_id})["status"] == "error"
