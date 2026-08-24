"""Ad-hoc probe: PDF export with a non-ASCII chapter title (AI-generated titles often
contain Japanese characters / em-dashes) -> Content-Disposition header encoding."""
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
TAG = "TEST_pdfuni_" + nid()[:6]

buf = io.BytesIO()
Image.new("RGB", (400, 600), (90, 30, 40)).save(buf, format="PNG")
url = requests.post(f"{API}/upload/character-reference",
                    files={"file": ("p.png", buf.getvalue(), "image/png")},
                    data={"client_id": TAG}, timeout=120).json()["url"]

for title in ["\u5915\u967d\u306e\u5263 \u2014 Dusk Blade", "Chapter / with:bad*chars?"]:
    mid, cid = nid(), nid()
    db.mangas.insert_one({"id": mid, "client_id": TAG, "title": TAG})
    db.chapters.insert_one({"id": cid, "manga_id": mid, "number": 1, "title": title, "status": "ready"})
    db.panels.insert_one({"id": nid(), "manga_id": mid, "chapter_id": cid, "scene_order": 0, "order": 0,
                          "status": "ready", "image_url": url, "bubbles": []})
    r = requests.get(f"{API}/chapters/{cid}/export/pdf", timeout=120)
    print(f"title={title!r} -> {r.status_code} ct={r.headers.get('content-type')} cd={r.headers.get('content-disposition')!r} body={r.text[:120] if r.status_code!=200 else ''}")
    db.panels.delete_many({"manga_id": mid}); db.chapters.delete_many({"manga_id": mid})

# missing 'number' field on chapter doc
mid, cid = nid(), nid()
db.mangas.insert_one({"id": mid, "client_id": TAG, "title": TAG})
db.chapters.insert_one({"id": cid, "manga_id": mid, "title": "No Number", "status": "ready"})
db.panels.insert_one({"id": nid(), "manga_id": mid, "chapter_id": cid, "scene_order": 0, "order": 0,
                      "status": "ready", "image_url": url, "bubbles": []})
r = requests.get(f"{API}/chapters/{cid}/export/pdf", timeout=120)
print("missing number ->", r.status_code, r.text[:120])

# panel whose image_url points at a deleted/invalid storage object
mid2, cid2 = nid(), nid()
db.mangas.insert_one({"id": mid2, "client_id": TAG, "title": TAG})
db.chapters.insert_one({"id": cid2, "manga_id": mid2, "number": 2, "title": "Broken", "status": "ready"})
db.panels.insert_one({"id": nid(), "manga_id": mid2, "chapter_id": cid2, "scene_order": 0, "order": 0,
                      "status": "ready", "image_url": "/api/files/ai-manga-studio/panels/does-not-exist.png",
                      "bubbles": []})
r = requests.get(f"{API}/chapters/{cid2}/export/pdf", timeout=120)
print("broken image ->", r.status_code, r.text[:160])

for m in (mid, mid2):
    for col in ("chapters", "panels"):
        db[col].delete_many({"manga_id": m})
db.mangas.delete_many({"client_id": TAG})
print("cleaned", db.mangas.count_documents({"client_id": TAG}))
