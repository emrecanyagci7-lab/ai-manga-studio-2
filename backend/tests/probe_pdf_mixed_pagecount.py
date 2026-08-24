"""Probe: exact PDF page count when some panel images are unreachable (FIXED-BUG-2)."""
import io
import uuid

import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from PIL import Image

API = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
benv = dotenv_values("/app/backend/.env")
db = MongoClient(benv["MONGO_URL"])[benv["DB_NAME"]]
nid = lambda: uuid.uuid4().hex
TAG = "TEST_mixed_" + nid()[:6]

buf = io.BytesIO()
Image.new("RGB", (400, 600), (10, 90, 60)).save(buf, format="PNG")
url = requests.post(f"{API}/upload/character-reference",
                    files={"file": ("p.png", buf.getvalue(), "image/png")},
                    data={"client_id": TAG}, timeout=120).json()["url"]

mid, cid = nid(), nid()
db.mangas.insert_one({"id": mid, "client_id": TAG, "title": TAG})
db.chapters.insert_one({"id": cid, "manga_id": mid, "number": 4, "title": "Mixed", "status": "ready"})
urls = [url, "/api/files/ai-manga-studio/panels/gone-1.png", url,
        "/api/files/ai-manga-studio/panels/gone-2.png"]
for order, u in enumerate(urls):
    db.panels.insert_one({"id": nid(), "manga_id": mid, "chapter_id": cid, "scene_order": 0,
                          "order": order, "status": "ready", "image_url": u, "bubbles": []})

r = requests.get(f"{API}/chapters/{cid}/export/pdf", timeout=180)
print("status:", r.status_code, "ct:", r.headers.get("content-type"))
print("cd:", r.headers.get("content-disposition"))
if r.status_code == 200:
    open("/tmp/mixed.pdf", "wb").write(r.content)
    from pypdf import PdfReader
    print("pages:", len(PdfReader("/tmp/mixed.pdf").pages), "size:", len(r.content))

for col in ("chapters", "panels"):
    db[col].delete_many({"manga_id": mid})
db.mangas.delete_many({"client_id": TAG})
print("cleaned", db.mangas.count_documents({"client_id": TAG}))
