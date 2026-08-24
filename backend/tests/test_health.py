# Module: server.py — health / root / explore basic endpoints
from conftest import API


class TestHealth:
    def test_health(self, api_client):
        r = api_client.get(f"{API}/health", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert isinstance(data.get("time"), str)

    def test_root(self, api_client):
        r = api_client.get(f"{API}/", timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    def test_explore_shape(self, api_client):
        r = api_client.get(f"{API}/mangas/explore", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "mangas" in body
        assert isinstance(body["mangas"], list)

    def test_get_manga_404(self, api_client):
        r = api_client.get(f"{API}/mangas/does-not-exist-xyz", timeout=30)
        assert r.status_code == 404, r.text

    def test_job_404(self, api_client):
        r = api_client.get(f"{API}/jobs/nope-xyz", timeout=30)
        assert r.status_code == 404, r.text

    def test_character_404(self, api_client):
        r = api_client.post(f"{API}/characters/nope-xyz/generate-portrait", timeout=60)
        assert r.status_code == 404, r.text

    def test_chapter_generate_404(self, api_client):
        r = api_client.post(f"{API}/chapters/nope-xyz/generate", timeout=30)
        assert r.status_code == 404, r.text

    def test_file_404(self, api_client):
        r = api_client.get(f"{API}/files/ai-manga-studio/nope/none.png", timeout=60)
        assert r.status_code == 404, r.text

    def test_create_manga_validation(self, api_client):
        # missing required client_id / idea
        r = api_client.post(f"{API}/mangas", json={"genre": "Fantasy"}, timeout=60)
        assert r.status_code == 422, r.text
