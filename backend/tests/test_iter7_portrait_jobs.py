"""Iteration-7: portrait generation converted to an async job pattern.

Fix under test:
  POST /api/characters/{id}/generate-portrait now returns {job_id} immediately
  (no longer blocks behind the Pollinations semaphore -> no more public-ingress 502).
  Progress is tracked via GET /api/jobs/{job_id} (and /stream for SSE).

Covered:
  - fast non-blocking response (<2s) through the PUBLIC ingress URL
  - 404 for unknown character validated BEFORE job creation (no job row written)
  - job document shape (type/target_id/manga_id/status/progress)
  - full happy path: poll until done -> character.reference_image_url set,
    file on disk >5KB with valid PNG/JPEG magic bytes, served over /api/files
  - 3 PARALLEL requests through the public URL: all HTTP 200, distinct job_ids,
    all reach status=done with 3 distinct images on disk (no 502)
  - portraits succeed even though GOOGLE_API_KEY is empty (image-only path)
"""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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

TAG = "TEST_it7_" + uuid.uuid4().hex[:8]
JOB_TIMEOUT = 240


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


def _seed(mdb, suffix, specs):
    manga_id = nid()
    mdb.mangas.insert_one({
        "id": manga_id,
        "client_id": f"{TAG}-{suffix}",
        "title": "TEST it7 portrait jobs",
        "art_style": "Manga-inspired",
        "plan_status": "done",
        "stats": {},
    })
    chars = []
    for name, appearance in specs:
        cid = nid()
        mdb.characters.insert_one({
            "id": cid, "manga_id": manga_id, "name": name,
            "appearance": appearance, "personality": "determined",
        })
        chars.append(cid)
    return manga_id, chars


def poll_job(http, job_id, timeout=JOB_TIMEOUT):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = http.get(f"{API}/jobs/{job_id}", timeout=30)
        assert r.status_code == 200, f"job poll failed: {r.status_code} {r.text[:300]}"
        last = r.json()
        assert "_id" not in last
        if last["status"] in ("done", "error"):
            return last
        time.sleep(2)
    return last


def assert_image_on_disk(url):
    assert url.startswith("/api/files/ai-manga-studio/portraits/"), url
    on_disk = STORAGE_ROOT / url.replace("/api/files/", "")
    assert on_disk.exists(), f"missing on disk: {on_disk}"
    size = on_disk.stat().st_size
    assert size > 5000, f"image too small ({size}): {on_disk}"
    head = on_disk.read_bytes()[:8]
    assert head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n", head.hex()
    return size


class TestPortraitJobContract:
    def test_returns_job_id_immediately(self, http, mdb):
        _, (char_id,) = _seed(mdb, "fast", [("Kenji", "young samurai, scar on cheek, grey kimono")])
        t0 = time.time()
        r = http.post(f"{API}/characters/{char_id}/generate-portrait", timeout=30)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        assert set(body.keys()) == {"job_id"}, body
        assert isinstance(body["job_id"], str) and len(body["job_id"]) > 8
        assert elapsed < 2.0, f"endpoint blocked for {elapsed:.2f}s (expected <2s)"
        print(f"POST returned job_id in {elapsed*1000:.0f}ms")

        job = http.get(f"{API}/jobs/{body['job_id']}", timeout=30).json()
        assert job["type"] == "portrait"
        assert job["target_id"] == char_id
        assert job["manga_id"]
        assert job["status"] in ("queued", "running", "done")
        assert isinstance(job["progress"], int)

        final = poll_job(http, body["job_id"])
        assert final["status"] == "done", f"job did not finish: {final}"
        assert final["progress"] == 100
        assert final.get("error") in (None, "")

        ch = http.get(f"{API}/characters/{char_id}", timeout=30)
        if ch.status_code == 404:  # no single-character GET route -> fall back to DB
            doc = mdb.characters.find_one({"id": char_id})
        else:
            doc = ch.json()
        url = doc["reference_image_url"]
        size = assert_image_on_disk(url)
        assert doc["user_uploaded_reference"] is False
        g = http.get(f"{API}/files/{url.replace('/api/files/', '')}", timeout=60)
        assert g.status_code == 200
        assert g.headers["content-type"].startswith("image/")
        print(f"portrait done: {size} bytes, GOOGLE_API_KEY empty -> Pollinations-only path OK")

    def test_404_for_unknown_character_before_job_creation(self, http, mdb):
        ghost = nid()
        before = mdb.generation_jobs.count_documents({"target_id": ghost})
        r = http.post(f"{API}/characters/{ghost}/generate-portrait", timeout=30)
        assert r.status_code == 404, f"{r.status_code} {r.text[:300]}"
        assert "bulunamadı" in r.json().get("detail", "")
        assert mdb.generation_jobs.count_documents({"target_id": ghost}) == before

    def test_unknown_job_id_returns_404(self, http):
        r = http.get(f"{API}/jobs/{nid()}", timeout=30)
        assert r.status_code == 404, r.text[:200]


def _post(char_id):
    s = requests.Session()
    t0 = time.time()
    try:
        r = s.post(f"{API}/characters/{char_id}/generate-portrait", timeout=60)
        return {"char_id": char_id, "status": r.status_code, "body": r.text[:200],
                "json": (r.json() if r.headers.get("content-type", "").startswith("application/json") else None),
                "elapsed": time.time() - t0}
    except Exception as e:  # noqa: BLE001
        return {"char_id": char_id, "status": -1, "body": f"{type(e).__name__}: {e}",
                "json": None, "elapsed": time.time() - t0}
    finally:
        s.close()


class TestPublicUrlConcurrency:
    """3 parallel portrait requests through the PUBLIC ingress URL must all return
    HTTP 200 quickly (previously 502 because of the semaphore-induced blocking)."""

    def test_three_parallel_requests_all_200_and_complete(self, http, mdb):
        _, chars = _seed(mdb, "conc", [
            ("Kenji", "young male samurai, short black hair, scar on left cheek, worn grey kimono"),
            ("Aiko", "teenage girl, long silver hair, red hair ribbon, school uniform"),
            ("Ryu", "tall old monk, bald, long white beard, brown robes, wooden staff"),
        ])
        with ThreadPoolExecutor(max_workers=3) as ex:
            results = list(ex.map(_post, chars))
        for res in results:
            print(f"  {res['char_id'][:8]} status={res['status']} {res['elapsed']:.2f}s {res['body'][:120]}")

        bad = [r for r in results if r["status"] != 200]
        assert not bad, f"non-200 responses (502 regression?): {[(b['status'], b['body']) for b in bad]}"
        slow = [r for r in results if r["elapsed"] >= 2.0]
        assert not slow, f"requests slower than 2s: {[(s['char_id'][:8], s['elapsed']) for s in slow]}"

        job_ids = [r["json"]["job_id"] for r in results]
        assert len(set(job_ids)) == 3, job_ids

        finals = [poll_job(http, jid, timeout=420) for jid in job_ids]
        errs = [f for f in finals if f["status"] != "done"]
        assert not errs, f"jobs not done: {[(e['id'][:8], e['status'], e.get('error')) for e in errs]}"

        urls = []
        for cid in chars:
            doc = mdb.characters.find_one({"id": cid})
            url = doc.get("reference_image_url")
            assert url, f"character {cid[:8]} has no reference_image_url"
            assert_image_on_disk(url)
            assert doc["user_uploaded_reference"] is False
            urls.append(url)
        assert len(set(urls)) == 3, f"urls not distinct: {urls}"
        print(f"3 parallel portraits completed: {urls}")
