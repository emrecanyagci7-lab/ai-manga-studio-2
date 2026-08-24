# Module: server.py — edge cases / validation gaps.
# NOTE: tests in this file assert the CORRECT expected behaviour. Failures here are
# real product defects reported to the developer agent (missing 404s / validation).
import pytest
import requests
from conftest import API


class TestMissingResourceHandling:
    def test_rename_missing_manga_returns_404(self, api_client):
        r = api_client.patch(f"{API}/mangas/ghost-id-xyz/rename", json={"title": "X"}, timeout=30)
        assert r.status_code == 404, f"got {r.status_code} {r.text} - silent success on missing manga"

    def test_publish_missing_manga_returns_404(self, api_client):
        r = api_client.post(f"{API}/mangas/ghost-id-xyz/publish", json={"is_published": True}, timeout=30)
        assert r.status_code == 404, f"got {r.status_code} {r.text} - silent success on missing manga"

    def test_delete_missing_manga_returns_404(self, api_client):
        r = api_client.delete(f"{API}/mangas/ghost-id-xyz", timeout=30)
        assert r.status_code == 404, f"got {r.status_code} {r.text} - silent success on missing manga"

    def test_bubbles_missing_panel_returns_404(self, api_client):
        r = api_client.patch(f"{API}/panels/ghost-id-xyz/bubbles", json={"bubbles": []}, timeout=30)
        assert r.status_code == 404, f"got {r.status_code} {r.text} - silent success on missing panel"


class TestInputValidation:
    def test_chapter_count_zero_rejected(self, api_client):
        r = api_client.post(f"{API}/mangas", json={
            "idea": "TEST_validation idea", "chapter_count": 0, "client_id": "TEST_validation",
        }, timeout=180)
        if r.status_code == 200:
            mid = r.json()["manga"]["id"]
            api_client.delete(f"{API}/mangas/{mid}", timeout=30)
        assert r.status_code == 422, "chapter_count=0 accepted -> manga created with zero chapters"

    def test_empty_idea_rejected(self, api_client):
        r = api_client.post(f"{API}/mangas", json={"idea": "", "client_id": "TEST_validation"}, timeout=180)
        if r.status_code == 200:
            mid = r.json()["manga"]["id"]
            api_client.delete(f"{API}/mangas/{mid}", timeout=30)
        assert r.status_code == 422, f"empty idea returned {r.status_code} (expected 422 validation error)"


class TestJobStream:
    def test_stream_missing_job(self, api_client):
        r = requests.get(f"{API}/jobs/ghost-job-xyz/stream", timeout=30, stream=True)
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("text/event-stream")
        first = next(r.iter_lines(decode_unicode=True))
        assert "error" in first, first
        r.close()


class TestUploadEndpoint:
    def test_generic_upload_requires_client_id(self, api_client):
        files = {"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")}
        r = api_client.post(f"{API}/upload/character-reference", files=files, timeout=60)
        assert r.status_code == 422, r.text

    def test_generic_upload_rejects_bad_ext(self, api_client):
        files = {"file": ("a.txt", b"hello", "text/plain")}
        r = api_client.post(f"{API}/upload/character-reference", files=files,
                            data={"client_id": "TEST_upload"}, timeout=60)
        assert r.status_code == 400, r.text

    def test_generic_upload_ok(self, api_client):
        import base64
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
        )
        files = {"file": ("a.png", png, "image/png")}
        r = api_client.post(f"{API}/upload/character-reference", files=files,
                            data={"client_id": "TEST_upload"}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["url"] == f"/api/files/{body['storage_path']}"
        base = API.rsplit("/api", 1)[0]
        g = api_client.get(f"{base}{body['url']}", timeout=60)
        assert g.status_code == 200
        assert g.headers["Content-Type"].startswith("image/")
        assert g.content == png
