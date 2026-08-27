"""Iteration-6: hardening verification for the Pollinations 429 flake.

Fix under test (ai_service.generate_image):
  - global asyncio.Semaphore(1) serializes Pollinations calls
  - backoffs [5, 15, 30]
  - Retry-After honored on HTTP 429

Test: seed 1 manga + 3 characters, POST /api/characters/{id}/generate-portrait
for all 3 CONCURRENTLY. All 3 must return 200 with distinct reference_image_urls
and real image files on disk.
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

TAG = "TEST_it6_" + uuid.uuid4().hex[:8]


def nid():
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def mdb():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module", autouse=True)
def cleanup(mdb):
    yield
    ids = [m["id"] for m in mdb.mangas.find({"client_id": {"$regex": f"^{TAG}"}}, {"id": 1})]
    for col in ("chapters", "panels", "scenes", "characters", "generation_jobs", "story_memory"):
        mdb[col].delete_many({"manga_id": {"$in": ids}})
    mdb.mangas.delete_many({"client_id": {"$regex": f"^{TAG}"}})


def _seed_manga_with_3_chars(mdb, suffix):
    manga_id = nid()
    mdb.mangas.insert_one({
        "id": manga_id,
        "client_id": f"{TAG}-{suffix}",
        "title": "TEST it6 concurrency",
        "art_style": "Manga-inspired",
        "plan_status": "done",
        "stats": {},
    })
    chars = []
    specs = [
        ("Kenji", "young male samurai, short black hair, scar on left cheek, worn grey kimono"),
        ("Aiko", "teenage girl, long silver hair, red hair ribbon, school uniform"),
        ("Ryu", "tall old monk, bald, long white beard, brown robes, wooden staff"),
    ]
    for name, appearance in specs:
        cid = nid()
        mdb.characters.insert_one({
            "id": cid, "manga_id": manga_id, "name": name,
            "appearance": appearance, "personality": "determined",
        })
        chars.append(cid)
    return manga_id, chars


def _portrait(char_id):
    s = requests.Session()
    t0 = time.time()
    try:
        r = s.post(f"{API}/characters/{char_id}/generate-portrait", timeout=60)
        return {"char_id": char_id, "status": r.status_code, "body": r.text[:300],
                "json": (r.json() if r.headers.get("content-type", "").startswith("application/json") else None),
                "elapsed": time.time() - t0}
    except Exception as e:  # noqa: BLE001
        return {"char_id": char_id, "status": -1, "body": f"{type(e).__name__}: {e}",
                "json": None, "elapsed": time.time() - t0}
    finally:
        s.close()


def _wait_job(job_id, timeout=420):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{API}/jobs/{job_id}", timeout=30)
        assert r.status_code == 200, r.text[:300]
        last = r.json()
        if last["status"] in ("done", "error"):
            return last
        time.sleep(2)
    return last


def _run_concurrent_round(mdb, suffix):
    _, chars = _seed_manga_with_3_chars(mdb, suffix)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(_portrait, chars))
    total = time.time() - t0
    print(f"\n[{suffix}] wall time {total:.1f}s")
    for res in results:
        print(f"  [{suffix}] {res['char_id'][:8]} status={res['status']} "
              f"{res['elapsed']:.1f}s body={res['body'][:160]}")
    return results, total


def _assert_all_ok(results, mdb):
    bad = [r for r in results if r["status"] != 200]
    assert not bad, f"non-200 portrait responses: {[(b['status'], b['body']) for b in bad]}"

    # iter7: endpoint is job-based -> {job_id}; poll each job to completion
    job_ids = [r["json"]["job_id"] for r in results]
    assert len(set(job_ids)) == 3, f"job_ids not distinct: {job_ids}"
    finals = [_wait_job(j) for j in job_ids]
    notdone = [f for f in finals if f["status"] != "done"]
    assert not notdone, f"jobs not done: {[(f['id'][:8], f['status'], f.get('error')) for f in notdone]}"

    urls = []
    for r in results:
        ch = mdb.characters.find_one({"id": r["char_id"]})
        url = ch.get("reference_image_url")
        assert url, f"no reference_image_url for {r['char_id'][:8]}"
        urls.append(url)
        assert ch["user_uploaded_reference"] is False
    assert len(set(urls)) == 3, f"reference_image_urls not distinct: {urls}"
    for url in urls:
        assert url.startswith("/api/files/ai-manga-studio/portraits/"), url
        on_disk = STORAGE_ROOT / url.replace("/api/files/", "")
        assert on_disk.exists(), f"missing on disk: {on_disk}"
        size = on_disk.stat().st_size
        assert size > 5000, f"image too small ({size}): {on_disk}"
        head = on_disk.read_bytes()[:8]
        assert head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n", head.hex()


class TestConcurrentPortraits:
    """Run the concurrent-portrait scenario twice to confirm stability."""

    def test_round_1_three_parallel_portraits(self, mdb):
        results, total = _run_concurrent_round(mdb, "r1")
        _assert_all_ok(results, mdb)
        # semaphore serializes: total ~= sum of individual server-side times (intended tradeoff)
        print(f"round1 total={total:.1f}s")

    def test_round_2_three_parallel_portraits(self, mdb):
        results, total = _run_concurrent_round(mdb, "r2")
        _assert_all_ok(results, mdb)
        print(f"round2 total={total:.1f}s")


class TestSemaphoreAndBackoffWiring:
    """Unit-level checks of the hardening code itself."""

    def test_semaphore_and_backoffs_present(self):
        import asyncio
        import inspect
        import sys
        sys.path.insert(0, "/app/backend")
        import ai_service

        assert isinstance(ai_service._pollinations_lock, asyncio.Semaphore)
        src = inspect.getsource(ai_service.generate_image)
        assert "_pollinations_lock" in src
        assert "[5, 15, 30]" in src
        assert "Retry-After" in src

    def test_retry_after_header_honored_on_429(self, monkeypatch):
        """Simulate 429 with Retry-After: 1 -> generate_image must sleep the header value."""
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        import ai_service
        import requests as rq

        calls = {"n": 0}
        sleeps = []

        def fake_fetch(prompt, seed):
            calls["n"] += 1
            if calls["n"] == 1:
                resp = rq.Response()
                resp.status_code = 429
                resp.headers["Retry-After"] = "1"
                raise rq.HTTPError("429 Too Many Requests", response=resp)
            return b"\xff\xd8\xff" + b"x" * 5000

        real_sleep = asyncio.sleep

        async def fake_sleep(sec):
            sleeps.append(sec)
            await real_sleep(0)

        monkeypatch.setattr(ai_service, "_fetch_pollinations_sync", fake_fetch)
        monkeypatch.setattr(ai_service.asyncio, "sleep", fake_sleep)

        data = asyncio.run(ai_service.generate_image("p", session_id="it6-retry-after"))
        assert len(data) > 5000
        assert sleeps == [1], f"expected Retry-After honored (1s), got {sleeps}"
        assert calls["n"] == 2

    def test_backoff_used_when_no_retry_after(self, monkeypatch):
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        import ai_service
        import requests as rq

        calls = {"n": 0}
        sleeps = []

        def fake_fetch(prompt, seed):
            calls["n"] += 1
            resp = rq.Response()
            resp.status_code = 429
            raise rq.HTTPError("429", response=resp)

        real_sleep = asyncio.sleep

        async def fake_sleep(sec):
            sleeps.append(sec)
            await real_sleep(0)

        monkeypatch.setattr(ai_service, "_fetch_pollinations_sync", fake_fetch)
        monkeypatch.setattr(ai_service.asyncio, "sleep", fake_sleep)

        with pytest.raises(RuntimeError):
            asyncio.run(ai_service.generate_image("p", session_id="it6-backoff"))
        assert sleeps == [5, 15, 30], sleeps
        assert calls["n"] == 3
