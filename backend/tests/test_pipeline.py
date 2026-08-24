# Module: server.py — full pipeline: create manga (plan) -> portrait -> upload ref -> files
# -> chapter generate job -> panels -> bubbles -> publish -> explore -> rename -> delete
import base64
import time

import pytest
from conftest import API, CLIENT_ID, INTERNAL_API

STATE = {}

# 1x1 transparent PNG
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)

IDEA = "A ronin whose blade whispers the memories of every soul it cuts"


class TestFullPipeline:
    # ---- POST /api/mangas (story plan via Claude/Gemini) ----
    def test_00_create_manga_via_public_ingress(self, api_client):
        """Documents gateway behaviour: plan generation is synchronous and slow."""
        payload = {
            "idea": IDEA,
            "genre": "Fantasy",
            "art_style": "Manga-inspired",
            "chapter_count": 2,
            "creativity": "balanced",
            "client_id": CLIENT_ID,
        }
        t0 = time.time()
        r = api_client.post(f"{API}/mangas", json=payload, timeout=300)
        el = time.time() - t0
        print(f"public create_manga took {el:.1f}s status={r.status_code}")
        assert r.status_code == 200, (
            f"public ingress returned {r.status_code} after {el:.1f}s - gateway timeout "
            f"on synchronous LLM plan generation"
        )
        body = r.json()
        STATE["public_manga_id"] = body["manga"]["id"]

    def test_01_create_manga(self, api_client):
        payload = {
            "idea": IDEA,
            "genre": "Fantasy",
            "art_style": "Manga-inspired",
            "chapter_count": 2,
            "creativity": "balanced",
            "client_id": CLIENT_ID,
        }
        t0 = time.time()
        # via internal URL: public ingress times out at 60s (see test_00)
        r = api_client.post(f"{INTERNAL_API}/mangas", json=payload, timeout=300)
        elapsed = time.time() - t0
        print(f"create_manga took {elapsed:.1f}s status={r.status_code}")
        assert r.status_code == 200, r.text[:1000]
        body = r.json()
        assert set(["manga", "characters", "chapters"]).issubset(body.keys())

        manga = body["manga"]
        assert "_id" not in manga
        assert isinstance(manga["id"], str) and len(manga["id"]) > 0
        assert manga["client_id"] == CLIENT_ID
        assert manga["title"] and manga["title"] != "Untitled Manga"
        assert manga["logline"]
        assert manga["synopsis"]
        assert isinstance(manga["world"], dict) and manga["world"]
        assert manga["genre"] == "Fantasy"
        assert manga["art_style"] == "Manga-inspired"
        assert manga["chapter_count"] == 2
        assert manga["is_published"] is False

        chars = body["characters"]
        assert len(chars) >= 3, f"expected >=3 characters, got {len(chars)}"
        for c in chars:
            assert c["name"] and c["appearance"]
            assert c["manga_id"] == manga["id"]
            assert c["reference_image_url"] is None
            assert "_id" not in c

        chapters = body["chapters"]
        assert len(chapters) == 2, f"expected exactly 2 chapters, got {len(chapters)}"
        for ch in chapters:
            assert ch["title"] and ch["summary"]
            assert ch["status"] == "outline"
            assert "_id" not in ch

        STATE["manga_id"] = manga["id"]
        STATE["char_ids"] = [c["id"] for c in chars]
        STATE["chapter_id"] = sorted(chapters, key=lambda x: x["number"])[0]["id"]
        STATE["title"] = manga["title"]

    # ---- GET /api/mangas?client_id= ----
    def test_02_list_mangas(self, api_client):
        assert "manga_id" in STATE, "creation failed"
        r = api_client.get(f"{API}/mangas", params={"client_id": CLIENT_ID}, timeout=60)
        assert r.status_code == 200, r.text
        ids = [m["id"] for m in r.json()["mangas"]]
        assert STATE["manga_id"] in ids

    # ---- GET /api/mangas/{id} ----
    def test_03_get_manga(self, api_client):
        assert "manga_id" in STATE
        r = api_client.get(f"{API}/mangas/{STATE['manga_id']}", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["manga"]["id"] == STATE["manga_id"]
        assert len(body["characters"]) >= 3
        assert len(body["chapters"]) == 2
        numbers = [c["number"] for c in body["chapters"]]
        assert numbers == sorted(numbers)

    # ---- POST /api/characters/{id}/generate-portrait (Nano Banana) ----
    def test_04_generate_portrait(self, api_client):
        assert STATE.get("char_ids")
        cid = STATE["char_ids"][0]
        t0 = time.time()
        r = api_client.post(f"{API}/characters/{cid}/generate-portrait", timeout=300)
        print(f"portrait took {time.time()-t0:.1f}s status={r.status_code}")
        assert r.status_code == 200, r.text[:1000]
        url = r.json()["reference_image_url"]
        assert url.startswith("/api/files/"), url
        STATE["portrait_url"] = url

        # verify persisted
        g = api_client.get(f"{API}/mangas/{STATE['manga_id']}", timeout=60)
        char = [c for c in g.json()["characters"] if c["id"] == cid][0]
        assert char["reference_image_url"] == url
        assert char["user_uploaded_reference"] is False

    # ---- GET /api/files/{path} for generated portrait ----
    def test_05_fetch_portrait_bytes(self, api_client):
        url = STATE.get("portrait_url")
        assert url, "portrait not generated"
        r = api_client.get(f"{API.rsplit('/api',1)[0]}{url}", timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert r.headers["Content-Type"].startswith("image/"), r.headers["Content-Type"]
        assert len(r.content) > 1000, len(r.content)

    # ---- POST /api/characters/{id}/upload-reference ----
    def test_06_upload_reference(self, api_client):
        assert STATE.get("char_ids")
        cid = STATE["char_ids"][1]
        files = {"file": ("ref.png", TINY_PNG, "image/png")}
        r = api_client.post(f"{API}/characters/{cid}/upload-reference", files=files, timeout=120)
        assert r.status_code == 200, r.text[:500]
        url = r.json()["reference_image_url"]
        assert url.startswith("/api/files/")
        STATE["uploaded_url"] = url

        g = api_client.get(f"{API}/mangas/{STATE['manga_id']}", timeout=60)
        char = [c for c in g.json()["characters"] if c["id"] == cid][0]
        assert char["reference_image_url"] == url
        assert char["user_uploaded_reference"] is True

    def test_07_fetch_uploaded_reference(self, api_client):
        url = STATE.get("uploaded_url")
        assert url
        r = api_client.get(f"{API.rsplit('/api',1)[0]}{url}", timeout=120)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("image/")
        assert r.content == TINY_PNG

    def test_08_upload_reference_bad_type(self, api_client):
        cid = STATE["char_ids"][1]
        files = {"file": ("ref.txt", b"hello", "text/plain")}
        r = api_client.post(f"{API}/characters/{cid}/upload-reference", files=files, timeout=60)
        assert r.status_code == 400, r.text

    # ---- POST /api/chapters/{id}/generate + job polling ----
    def test_09_generate_chapter(self, api_client):
        assert STATE.get("chapter_id")
        r = api_client.post(f"{API}/chapters/{STATE['chapter_id']}/generate", timeout=60)
        assert r.status_code == 200, r.text
        job_id = r.json()["job_id"]
        assert isinstance(job_id, str) and job_id
        STATE["job_id"] = job_id

        deadline = time.time() + 900
        last = None
        while time.time() < deadline:
            j = api_client.get(f"{API}/jobs/{job_id}", timeout=60)
            assert j.status_code == 200, j.text
            doc = j.json()
            assert "_id" not in doc
            if (doc["progress"], doc["status"]) != last:
                print(f"job progress={doc['progress']} status={doc['status']} err={doc.get('error')}")
                last = (doc["progress"], doc["status"])
            if doc["status"] in ("done", "error"):
                STATE["job_final"] = doc
                break
            time.sleep(10)
        else:
            pytest.fail(f"Chapter generation did not finish in 900s; last={last}")

        doc = STATE["job_final"]
        assert doc["status"] == "done", f"job errored: {doc.get('error')}"
        assert doc["progress"] == 100

    def test_10_chapter_status_ready(self, api_client):
        assert STATE.get("job_final"), "job did not complete"
        r = api_client.get(f"{API}/mangas/{STATE['manga_id']}", timeout=60)
        ch = [c for c in r.json()["chapters"] if c["id"] == STATE["chapter_id"]][0]
        assert ch["status"] == "ready", ch
        assert ch["scenes_count"] > 0

    # ---- GET /api/chapters/{id}/panels ----
    def test_11_panels(self, api_client):
        assert STATE.get("job_final")
        r = api_client.get(f"{API}/chapters/{STATE['chapter_id']}/panels", timeout=60)
        assert r.status_code == 200, r.text
        panels = r.json()["panels"]
        assert len(panels) > 0, "no panels created"
        ready = [p for p in panels if p["status"] == "ready"]
        print(f"panels total={len(panels)} ready={len(ready)}")
        assert len(ready) > 0, "no panel images generated successfully"
        for p in panels:
            assert "_id" not in p
            assert isinstance(p["bubbles"], list)
        p0 = ready[0]
        assert p0["image_url"].startswith("/api/files/")
        STATE["panel_id"] = p0["id"]
        STATE["panel_image_url"] = p0["image_url"]

        # bubble schema check on any panel that has bubbles
        with_bubbles = [p for p in ready if p["bubbles"]]
        assert with_bubbles, "no panel has dialogue bubbles"
        b = with_bubbles[0]["bubbles"][0]
        for key in ("id", "text", "type", "x", "y", "width", "height"):
            assert key in b, f"bubble missing {key}: {b}"

    def test_12_panel_image_served(self, api_client):
        url = STATE.get("panel_image_url")
        assert url
        r = api_client.get(f"{API.rsplit('/api',1)[0]}{url}", timeout=120)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("image/")
        assert len(r.content) > 1000

    # ---- PATCH /api/panels/{id}/bubbles ----
    def test_13_update_bubbles(self, api_client):
        pid = STATE.get("panel_id")
        assert pid
        new_bubbles = [{
            "id": "b1", "text": "TEST_bubble", "type": "thought",
            "character": "Tester", "x": 0.2, "y": 0.3, "width": 0.4, "height": 0.2,
        }]
        r = api_client.patch(f"{API}/panels/{pid}/bubbles", json={"bubbles": new_bubbles}, timeout=60)
        assert r.status_code == 200, r.text
        g = api_client.get(f"{API}/chapters/{STATE['chapter_id']}/panels", timeout=60)
        panel = [p for p in g.json()["panels"] if p["id"] == pid][0]
        assert panel["bubbles"] == new_bubbles

    # ---- PATCH rename ----
    def test_14_rename(self, api_client):
        r = api_client.patch(f"{API}/mangas/{STATE['manga_id']}/rename", json={"title": "TEST_Renamed Manga"}, timeout=60)
        assert r.status_code == 200, r.text
        g = api_client.get(f"{API}/mangas/{STATE['manga_id']}", timeout=60)
        assert g.json()["manga"]["title"] == "TEST_Renamed Manga"

    # ---- POST publish + explore ----
    def test_15_publish_and_explore(self, api_client):
        r = api_client.post(f"{API}/mangas/{STATE['manga_id']}/publish", json={"is_published": True}, timeout=60)
        assert r.status_code == 200, r.text
        g = api_client.get(f"{API}/mangas/{STATE['manga_id']}", timeout=60)
        m = g.json()["manga"]
        assert m["is_published"] is True
        assert m["published_at"]

        e = api_client.get(f"{API}/mangas/explore", timeout=60)
        assert STATE["manga_id"] in [x["id"] for x in e.json()["mangas"]]

    def test_16_unpublish(self, api_client):
        r = api_client.post(f"{API}/mangas/{STATE['manga_id']}/publish", json={"is_published": False}, timeout=60)
        assert r.status_code == 200
        e = api_client.get(f"{API}/mangas/explore", timeout=60)
        assert STATE["manga_id"] not in [x["id"] for x in e.json()["mangas"]]

    def test_17_cover_url_set(self, api_client):
        g = api_client.get(f"{API}/mangas/{STATE['manga_id']}", timeout=60)
        assert g.json()["manga"]["cover_url"], "cover_url not set after chapter generation"

    # ---- DELETE cascade ----
    def test_18_delete_cascade(self, api_client):
        mid = STATE["manga_id"]
        r = api_client.delete(f"{API}/mangas/{mid}", timeout=60)
        assert r.status_code == 200, r.text
        assert api_client.get(f"{API}/mangas/{mid}", timeout=60).status_code == 404
        p = api_client.get(f"{API}/chapters/{STATE['chapter_id']}/panels", timeout=60)
        assert p.json()["panels"] == [], "panels not cascade-deleted"
        lst = api_client.get(f"{API}/mangas", params={"client_id": CLIENT_ID}, timeout=60)
        assert mid not in [m["id"] for m in lst.json()["mangas"]]
        STATE.pop("manga_id", None)


@pytest.fixture(scope="module", autouse=True)
def cleanup(api_client):
    yield
    for key in ("manga_id", "public_manga_id"):
        mid = STATE.get(key)
        if mid:
            api_client.delete(f"{API}/mangas/{mid}", timeout=60)
