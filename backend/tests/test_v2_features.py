"""Structural tests for v2 features: usage summary, panel cap, batch chapter generation,
PDF export, plus regression checks on existing endpoints.

NOTE: EMERGENT_LLM_KEY budget is exhausted -> NO test here triggers AI text/image generation.
All fixtures seed Mongo directly and clean up afterwards.
"""
import io
import os
import re
import time
import uuid
from urllib.parse import unquote

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

TAG = "TEST_v2_" + uuid.uuid4().hex[:8]


def nid():
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def mdb():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    yield s
    s.close()


@pytest.fixture(scope="module", autouse=True)
def cleanup(mdb):
    """Remove every doc created by this module (tagged via client_id / title prefix)."""
    yield
    ids = [m["id"] for m in mdb.mangas.find({"client_id": {"$regex": f"^{TAG}"}}, {"id": 1})]
    for col in ("mangas", "chapters", "panels", "scenes", "characters", "generation_jobs"):
        mdb[col].delete_many({"manga_id": {"$in": ids}})
    mdb.mangas.delete_many({"client_id": {"$regex": f"^{TAG}"}})
    mdb.panels.delete_many({"id": {"$regex": f"^{TAG}"}})


def seed_manga(mdb, client_id, **over):
    doc = {
        "id": nid(),
        "client_id": client_id,
        "title": f"{TAG} Manga",
        "logline": "l", "synopsis": "s", "world": {}, "themes": [],
        "genre": "Fantasy", "art_style": "Manga-inspired", "creativity": "balanced",
        "chapter_count": 5, "is_published": False, "published_at": None, "cover_url": None,
        "plan_status": "ready", "max_panels_per_chapter": 8,
        "stats": {"text_calls": 0, "image_calls": 0, "panels_generated": 0, "chapters_generated": 0},
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }
    doc.update(over)
    mdb.mangas.insert_one(dict(doc))
    return doc


def seed_chapter(mdb, manga_id, number=1, status="planned"):
    doc = {"id": nid(), "manga_id": manga_id, "number": number,
           "title": f"{TAG} Chapter {number}", "summary": "sum", "status": status,
           "created_at": "2026-01-01T00:00:00+00:00"}
    mdb.chapters.insert_one(dict(doc))
    return doc


# ---------------- Health / existing endpoints regression ----------------
class TestRegression:
    def test_health(self, http):
        r = http.get(f"{API}/health", timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert "time" in r.json()

    def test_root(self, http):
        r = http.get(f"{API}/", timeout=30)
        assert r.status_code == 200
        assert r.json()["service"] == "AI Manga Studio"

    def test_explore_returns_list(self, http):
        r = http.get(f"{API}/mangas/explore", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("mangas"), list)
        assert all(m.get("is_published") is True for m in body["mangas"])
        assert all("_id" not in m for m in body["mangas"])

    def test_list_mangas_filters_by_client_id(self, http, mdb):
        cid = f"{TAG}_list"
        mine = seed_manga(mdb, cid)
        seed_manga(mdb, f"{TAG}_other")
        r = http.get(f"{API}/mangas", params={"client_id": cid}, timeout=30)
        assert r.status_code == 200, r.text
        docs = r.json()["mangas"]
        assert [d["id"] for d in docs] == [mine["id"]]
        assert "_id" not in docs[0]

    def test_list_mangas_requires_client_id(self, http):
        r = http.get(f"{API}/mangas", timeout=30)
        assert r.status_code == 422, r.text

    def test_get_manga_404(self, http):
        r = http.get(f"{API}/mangas/{nid()}", timeout=30)
        assert r.status_code == 404

    def test_rename_404_and_validation(self, http, mdb):
        r = http.patch(f"{API}/mangas/{nid()}/rename", json={"title": "X"}, timeout=30)
        assert r.status_code == 404, r.text
        m = seed_manga(mdb, f"{TAG}_ren")
        r = http.patch(f"{API}/mangas/{m['id']}/rename", json={"title": ""}, timeout=30)
        assert r.status_code == 422, r.text
        r = http.patch(f"{API}/mangas/{m['id']}/rename", json={"title": f"{TAG} Renamed"}, timeout=30)
        assert r.status_code == 200, r.text
        assert mdb.mangas.find_one({"id": m["id"]})["title"] == f"{TAG} Renamed"

    def test_publish_404(self, http):
        r = http.post(f"{API}/mangas/{nid()}/publish", json={"is_published": True}, timeout=30)
        assert r.status_code == 404, r.text

    def test_delete_404(self, http):
        r = http.delete(f"{API}/mangas/{nid()}", timeout=30)
        assert r.status_code == 404, r.text

    def test_bubbles_404_and_validation(self, http, mdb):
        body = {"bubbles": [{"id": "b1", "text": "hi", "type": "speech", "character": "A",
                             "x": 0.1, "y": 0.1, "width": 0.3, "height": 0.15}]}
        r = http.patch(f"{API}/panels/{nid()}/bubbles", json=body, timeout=30)
        assert r.status_code == 404, r.text
        # missing required id field -> 422
        r = http.patch(f"{API}/panels/{nid()}/bubbles", json={"bubbles": [{"text": "x"}]}, timeout=30)
        assert r.status_code == 422, r.text


# ---------------- Usage summary ----------------
class TestUsageSummary:
    def test_fresh_client_all_zeros(self, http):
        r = http.get(f"{API}/usage/summary", params={"client_id": f"{TAG}_fresh"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["totals"].keys()) == {
            "text_calls", "image_calls", "panels_generated", "chapters_generated", "mangas"}
        assert all(v == 0 for v in body["totals"].values())
        assert body["estimated_credits_spent_usd"] == 0

    def test_missing_client_id_422(self, http):
        r = http.get(f"{API}/usage/summary", timeout=30)
        assert r.status_code == 422, r.text

    def test_aggregates_stats_across_mangas(self, http, mdb):
        cid = f"{TAG}_usage"
        seed_manga(mdb, cid, stats={"text_calls": 2, "image_calls": 3,
                                    "panels_generated": 3, "chapters_generated": 1})
        seed_manga(mdb, cid, stats={"text_calls": 1, "image_calls": 2,
                                    "panels_generated": 2, "chapters_generated": 1})
        r = http.get(f"{API}/usage/summary", params={"client_id": cid}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["totals"] == {"text_calls": 3, "image_calls": 5, "panels_generated": 5,
                                 "chapters_generated": 2, "mangas": 2}
        assert body["estimated_credits_spent_usd"] == pytest.approx(5 * 0.04 + 3 * 0.01, abs=1e-6)

    def test_handles_manga_without_stats_field(self, http, mdb):
        cid = f"{TAG}_nostats"
        m = seed_manga(mdb, cid)
        mdb.mangas.update_one({"id": m["id"]}, {"$unset": {"stats": ""}})
        r = http.get(f"{API}/usage/summary", params={"client_id": cid}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["totals"]["mangas"] == 1
        assert r.json()["totals"]["text_calls"] == 0


# ---------------- Panel cap ----------------
class TestPanelCap:
    def test_update_and_persist(self, http, mdb):
        m = seed_manga(mdb, f"{TAG}_cap")
        r = http.patch(f"{API}/mangas/{m['id']}/panel-cap",
                       json={"max_panels_per_chapter": 5}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "max_panels_per_chapter": 5}
        g = http.get(f"{API}/mangas/{m['id']}", timeout=30)
        assert g.status_code == 200
        assert g.json()["manga"]["max_panels_per_chapter"] == 5

    @pytest.mark.parametrize("value", [0, -1, 31, 100])
    def test_out_of_range_422(self, http, mdb, value):
        m = seed_manga(mdb, f"{TAG}_cap_bad")
        r = http.patch(f"{API}/mangas/{m['id']}/panel-cap",
                       json={"max_panels_per_chapter": value}, timeout=30)
        assert r.status_code == 422, f"value={value} -> {r.status_code} {r.text}"

    @pytest.mark.parametrize("value", [1, 30])
    def test_boundaries_accepted(self, http, mdb, value):
        m = seed_manga(mdb, f"{TAG}_cap_ok")
        r = http.patch(f"{API}/mangas/{m['id']}/panel-cap",
                       json={"max_panels_per_chapter": value}, timeout=30)
        assert r.status_code == 200, r.text
        assert mdb.mangas.find_one({"id": m["id"]})["max_panels_per_chapter"] == value

    def test_missing_field_422(self, http, mdb):
        m = seed_manga(mdb, f"{TAG}_cap_missing")
        r = http.patch(f"{API}/mangas/{m['id']}/panel-cap", json={}, timeout=30)
        assert r.status_code == 422, r.text

    def test_nonexistent_manga_404(self, http):
        r = http.patch(f"{API}/mangas/{nid()}/panel-cap",
                       json={"max_panels_per_chapter": 5}, timeout=30)
        assert r.status_code == 404, r.text


# ---------------- Batch chapter generation ----------------
class TestBatchGenerate:
    def test_nonexistent_manga_404(self, http):
        r = http.post(f"{API}/mangas/{nid()}/chapters/batch-generate",
                      json={"chapter_ids": [nid()]}, timeout=30)
        assert r.status_code == 404, r.text
        assert "Manga not found" in r.text

    def test_empty_chapter_ids_422(self, http, mdb):
        m = seed_manga(mdb, f"{TAG}_batch_empty")
        r = http.post(f"{API}/mangas/{m['id']}/chapters/batch-generate",
                      json={"chapter_ids": []}, timeout=30)
        assert r.status_code == 422, r.text

    def test_too_many_chapter_ids_422(self, http, mdb):
        m = seed_manga(mdb, f"{TAG}_batch_max")
        r = http.post(f"{API}/mangas/{m['id']}/chapters/batch-generate",
                      json={"chapter_ids": [nid() for _ in range(21)]}, timeout=30)
        assert r.status_code == 422, r.text

    def test_missing_body_422(self, http, mdb):
        m = seed_manga(mdb, f"{TAG}_batch_nobody")
        r = http.post(f"{API}/mangas/{m['id']}/chapters/batch-generate", json={}, timeout=30)
        assert r.status_code == 422, r.text

    def test_no_matching_chapters_404(self, http, mdb):
        m = seed_manga(mdb, f"{TAG}_batch_nomatch")
        r = http.post(f"{API}/mangas/{m['id']}/chapters/batch-generate",
                      json={"chapter_ids": [nid(), nid()]}, timeout=30)
        assert r.status_code == 404, r.text
        assert "No matching chapters" in r.text

    def test_chapters_from_other_manga_not_matched(self, http, mdb):
        m1 = seed_manga(mdb, f"{TAG}_batch_x1")
        m2 = seed_manga(mdb, f"{TAG}_batch_x2")
        foreign = seed_chapter(mdb, m2["id"], 1)
        r = http.post(f"{API}/mangas/{m1['id']}/chapters/batch-generate",
                      json={"chapter_ids": [foreign["id"]]}, timeout=30)
        assert r.status_code == 404, r.text

    def test_structural_response_and_job_docs(self, http, mdb):
        """AI workers will fail (exhausted key) - only structure/persistence is asserted."""
        m = seed_manga(mdb, f"{TAG}_batch_ok")
        c2 = seed_chapter(mdb, m["id"], 2)
        c1 = seed_chapter(mdb, m["id"], 1)
        r = http.post(f"{API}/mangas/{m['id']}/chapters/batch-generate",
                      json={"chapter_ids": [c2["id"], c1["id"]]}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("batch_id"), str) and body["batch_id"]
        jobs = body["jobs"]
        assert len(jobs) == 2
        # ordered by chapter number
        assert [j["chapter_number"] for j in jobs] == [1, 2]
        assert [j["chapter_id"] for j in jobs] == [c1["id"], c2["id"]]
        for j in jobs:
            assert isinstance(j["job_id"], str) and j["job_id"]
            jr = http.get(f"{API}/jobs/{j['job_id']}", timeout=30)
            assert jr.status_code == 200, jr.text
            jd = jr.json()
            assert jd["type"] == "chapter"
            assert jd["target_id"] == j["chapter_id"]
            assert jd["manga_id"] == m["id"]
            assert "_id" not in jd

        batch = http.get(f"{API}/jobs/{body['batch_id']}", timeout=30)
        assert batch.status_code == 200, batch.text
        bd = batch.json()
        assert bd["type"] == "batch"
        assert bd["target_id"] == m["id"]
        assert set(bd["child_jobs"]) == {j["job_id"] for j in jobs}
        assert "_id" not in bd

    def test_job_404(self, http):
        r = http.get(f"{API}/jobs/{nid()}", timeout=30)
        assert r.status_code == 404


# ---------------- PDF export ----------------
def _png_bytes(w=600, h=800):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (40, 60, 120)).save(buf, format="PNG")
    return buf.getvalue()


class TestPdfExport:
    def test_nonexistent_chapter_404(self, http):
        r = http.get(f"{API}/chapters/{nid()}/export/pdf", timeout=60)
        assert r.status_code == 404, r.text

    def test_chapter_without_panels_400(self, http, mdb):
        m = seed_manga(mdb, f"{TAG}_pdf_empty")
        c = seed_chapter(mdb, m["id"], 1, status="planned")
        r = http.get(f"{API}/chapters/{c['id']}/export/pdf", timeout=60)
        assert r.status_code == 400, r.text
        assert "no ready panels" in r.text.lower()

    def test_chapter_with_only_pending_panels_400(self, http, mdb):
        m = seed_manga(mdb, f"{TAG}_pdf_pending")
        c = seed_chapter(mdb, m["id"], 1)
        mdb.panels.insert_one({"id": f"{TAG}p{nid()}", "manga_id": m["id"], "chapter_id": c["id"],
                               "scene_order": 0, "order": 0, "status": "pending",
                               "image_url": None, "bubbles": []})
        r = http.get(f"{API}/chapters/{c['id']}/export/pdf", timeout=60)
        assert r.status_code == 400, r.text

    def test_happy_path_pdf_with_bubbles(self, http, mdb):
        """Uploads a real image to storage (no AI), seeds two ready panels, exports PDF."""
        cid = f"{TAG}_pdf_ok"
        up = http.post(f"{API}/upload/character-reference",
                       files={"file": ("seed.png", _png_bytes(), "image/png")},
                       data={"client_id": cid}, timeout=120)
        if up.status_code != 200:
            pytest.skip(f"Storage upload unavailable ({up.status_code}): {up.text[:200]}")
        image_url = up.json()["url"]

        m = seed_manga(mdb, cid)
        c = seed_chapter(mdb, m["id"], 3, status="ready")
        bubbles = [
            {"id": "b1", "text": "Hello there, this is a fairly long speech line.",
             "type": "speech", "character": "A", "x": 0.05, "y": 0.05, "width": 0.5, "height": 0.15},
            {"id": "b2", "text": "BOOM", "type": "sfx", "character": "",
             "x": 0.5, "y": 0.5, "width": 0.3, "height": 0.1},
            {"id": "b3", "text": "hmm...", "type": "thought", "character": "A",
             "x": 0.1, "y": 0.7, "width": 0.35, "height": 0.15},
            {"id": "b4", "text": "psst", "type": "whisper", "character": "B",
             "x": 0.55, "y": 0.75, "width": 0.3, "height": 0.12},
            {"id": "b5", "text": "Later that day...", "type": "narration", "character": "",
             "x": 0.05, "y": 0.4, "width": 0.4, "height": 0.1},
            {"id": "b6", "text": "STOP!", "type": "shout", "character": "B",
             "x": 0.6, "y": 0.2, "width": 0.3, "height": 0.12},
        ]
        for order, bl in enumerate([bubbles, []]):
            mdb.panels.insert_one({
                "id": f"{TAG}p{nid()}", "manga_id": m["id"], "chapter_id": c["id"],
                "scene_order": 0, "order": order, "status": "ready",
                "image_url": image_url, "bubbles": bl,
            })

        r = http.get(f"{API}/chapters/{c['id']}/export/pdf", timeout=180)
        assert r.status_code == 200, r.text[:500]
        assert r.headers.get("content-type", "").startswith("application/pdf"), r.headers
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd and ".pdf" in cd, cd
        assert r.content[:5] == b"%PDF-", r.content[:20]
        assert len(r.content) > 2000
        # 2 panels -> 2 pages
        assert r.content.count(b"/Type /Page") >= 2 or r.content.count(b"/Type/Page") >= 2


# ---------------- PDF export edge cases (known bugs, see report) ----------------
class TestPdfExportEdgeCases:
    @pytest.fixture(scope="class")
    def seeded_image_url(self, http):
        up = http.post(f"{API}/upload/character-reference",
                       files={"file": ("edge.png", _png_bytes(300, 400), "image/png")},
                       data={"client_id": f"{TAG}_edge"}, timeout=120)
        if up.status_code != 200:
            pytest.skip(f"Storage upload unavailable ({up.status_code})")
        return up.json()["url"]

    def _seed_ready_chapter(self, mdb, image_url, **ch_over):
        m = seed_manga(mdb, f"{TAG}_edge")
        ch = {"id": nid(), "manga_id": m["id"], "number": 1, "title": "Edge",
              "status": "ready", "created_at": "2026-01-01T00:00:00+00:00"}
        ch.update(ch_over)
        mdb.chapters.insert_one(dict(ch))
        mdb.panels.insert_one({"id": f"{TAG}p{nid()}", "manga_id": m["id"], "chapter_id": ch["id"],
                               "scene_order": 0, "order": 0, "status": "ready",
                               "image_url": image_url, "bubbles": []})
        return ch

    def test_non_ascii_chapter_title(self, http, mdb, seeded_image_url):
        """FIXED-BUG-1: AI titles contain Japanese chars; header must not blow up."""
        ch = self._seed_ready_chapter(mdb, seeded_image_url, title="\u5915\u967d\u306e\u5263 \u2014 Dusk Blade")
        r = http.get(f"{API}/chapters/{ch['id']}/export/pdf", timeout=120)
        assert r.status_code == 200, f"non-ASCII title -> {r.status_code}: {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith("application/pdf")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd, cd
        # ASCII fallback filename present and pure-ASCII
        m = re.search(r'filename="([^"]+)"', cd)
        assert m, f"no ascii filename in {cd!r}"
        ascii_fn = m.group(1)
        assert ascii_fn.isascii() and ascii_fn.endswith(".pdf"), ascii_fn
        # RFC 5987 UTF-8 variant present and decodes back to the original title
        m2 = re.search(r"filename\*=UTF-8''([^;]+)", cd)
        assert m2, f"no RFC5987 filename* in {cd!r}"
        assert "\u5915\u967d\u306e\u5263" in unquote(m2.group(1)), m2.group(1)
        assert r.content[:5] == b"%PDF-"

    def test_mixed_valid_and_broken_panel_images_exports_only_valid(self, http, mdb, seeded_image_url):
        """FIXED-BUG-2: per-panel try/except -> stale image must not 500 the export."""
        m = seed_manga(mdb, f"{TAG}_edge")
        ch = seed_chapter(mdb, m["id"], 7, status="ready")
        urls = [seeded_image_url, "/api/files/ai-manga-studio/panels/does-not-exist.png",
                seeded_image_url, None]
        for order, u in enumerate(urls):
            mdb.panels.insert_one({"id": f"{TAG}p{nid()}", "manga_id": m["id"],
                                   "chapter_id": ch["id"], "scene_order": 0, "order": order,
                                   "status": "ready", "image_url": u, "bubbles": []})
        r = http.get(f"{API}/chapters/{ch['id']}/export/pdf", timeout=180)
        assert r.status_code == 200, f"mixed panels -> {r.status_code}: {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"
        pages = max(r.content.count(b"/Type /Page\n"), r.content.count(b"/Type /Page"),
                    r.content.count(b"/Type/Page"))
        assert pages >= 2, f"expected only reachable panels rendered, pages={pages}"

    def test_all_broken_panel_images_returns_502(self, http, mdb):
        """FIXED-BUG-2: if every panel image is unreachable -> 502, not 500."""
        m = seed_manga(mdb, f"{TAG}_edge")
        ch = seed_chapter(mdb, m["id"], 8, status="ready")
        for order in range(2):
            mdb.panels.insert_one({
                "id": f"{TAG}p{nid()}", "manga_id": m["id"], "chapter_id": ch["id"],
                "scene_order": 0, "order": order, "status": "ready",
                "image_url": f"/api/files/ai-manga-studio/panels/missing-{order}.png",
                "bubbles": []})
        r = http.get(f"{API}/chapters/{ch['id']}/export/pdf", timeout=180)
        assert r.status_code == 502, f"all-broken -> {r.status_code}: {r.text[:200]}"
        # NOTE: the public ingress (Cloudflare) replaces 502 bodies with its own HTML error
        # page, so the backend's JSON detail is NOT visible to clients. Body asserted
        # against the backend directly instead.
        internal = requests.get(
            f"http://localhost:8001/api/chapters/{ch['id']}/export/pdf", timeout=180)
        assert internal.status_code == 502, internal.status_code
        assert "unavailable" in internal.text.lower(), internal.text[:200]

    def test_chapter_missing_number_field(self, http, mdb, seeded_image_url):
        m = seed_manga(mdb, f"{TAG}_edge")
        cid = nid()
        mdb.chapters.insert_one({"id": cid, "manga_id": m["id"], "title": "No Number",
                                 "status": "ready", "created_at": "2026-01-01T00:00:00+00:00"})
        mdb.panels.insert_one({"id": f"{TAG}p{nid()}", "manga_id": m["id"], "chapter_id": cid,
                               "scene_order": 0, "order": 0, "status": "ready",
                               "image_url": seeded_image_url, "bubbles": []})
        r = http.get(f"{API}/chapters/{cid}/export/pdf", timeout=120)
        assert r.status_code != 500, f"missing 'number' -> 500 (KeyError): {r.text[:200]}"

    def test_unreachable_panel_image_returns_graceful_error(self, http, mdb):
        ch = self._seed_ready_chapter(
            mdb, "/api/files/ai-manga-studio/panels/does-not-exist.png")
        r = http.get(f"{API}/chapters/{ch['id']}/export/pdf", timeout=120)
        assert r.status_code != 500, f"missing storage object -> unhandled 500: {r.text[:200]}"
        assert r.status_code == 502, r.status_code

    def test_illegal_chars_in_title_sanitized(self, http, mdb, seeded_image_url):
        ch = self._seed_ready_chapter(mdb, seeded_image_url, title="Chapter / with:bad*chars?")
        r = http.get(f"{API}/chapters/{ch['id']}/export/pdf", timeout=120)
        assert r.status_code == 200, r.text[:200]
        cd = r.headers.get("content-disposition", "")
        m = re.search(r'filename="([^"]+)"', cd)
        assert m, cd
        assert "/" not in m.group(1) and "*" not in m.group(1), m.group(1)


# ---------------- Batch job outcome aggregation (FIXED-BUG-3) ----------------
class TestBatchLifecycle:
    def test_all_children_fail_batch_not_done(self, http, mdb):
        """AI key exhausted -> every child job errors. Batch must NOT report done."""
        m = seed_manga(mdb, f"{TAG}_batch_life")
        chs = [seed_chapter(mdb, m["id"], n) for n in (1, 2)]
        r = http.post(f"{API}/mangas/{m['id']}/chapters/batch-generate",
                      json={"chapter_ids": [c["id"] for c in chs]}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        batch_id = body["batch_id"]
        child_ids = [j["job_id"] for j in body["jobs"]]

        bd = None
        for _ in range(45):
            jr = http.get(f"{API}/jobs/{batch_id}", timeout=30)
            assert jr.status_code == 200, jr.text
            bd = jr.json()
            if bd["status"] in ("done", "error", "partial"):
                break
            time.sleep(2)
        assert bd is not None and bd["status"] in ("done", "error", "partial"), bd

        children = [http.get(f"{API}/jobs/{c}", timeout=30).json() for c in child_ids]
        failed_children = [c for c in children if c["status"] == "error"]
        print("children statuses:", [c["status"] for c in children])
        print("batch doc:", {k: bd.get(k) for k in
                             ("status", "progress", "failed_count", "total_count", "error")})

        assert bd.get("total_count") == len(child_ids), bd
        assert bd.get("failed_count") == len(failed_children), bd
        if failed_children and len(failed_children) == len(children):
            assert bd["status"] == "error", f"all children failed but batch={bd['status']}"
            assert bd.get("error"), "batch error message not populated"
        elif failed_children:
            assert bd["status"] == "partial", bd["status"]
        else:
            pytest.skip("No child job failed (AI key working) - all-fail path not exercised")
