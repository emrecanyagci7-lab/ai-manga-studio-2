"""Ad-hoc perf probe: PDF export latency with a full 8-panel chapter (public ingress)."""
import time
import uuid

import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from PIL import Image
import io

API = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
benv = dotenv_values("/app/backend/.env")
db = MongoClient(benv["MONGO_URL"])[benv["DB_NAME"]]
nid = lambda: uuid.uuid4().hex
TAG = "TEST_pdfperf_" + nid()[:6]

buf = io.BytesIO()
Image.new("RGB", (1024, 1536), (30, 40, 90)).save(buf, format="PNG")
up = requests.post(f"{API}/upload/character-reference",
                   files={"file": ("p.png", buf.getvalue(), "image/png")},
                   data={"client_id": TAG}, timeout=120)
print("upload", up.status_code)
url = up.json()["url"]

mid, cid = nid(), nid()
db.mangas.insert_one({"id": mid, "client_id": TAG, "title": TAG})
db.chapters.insert_one({"id": cid, "manga_id": mid, "number": 1, "title": "Perf Chapter", "status": "ready"})
for i in range(8):
    db.panels.insert_one({"id": nid(), "manga_id": mid, "chapter_id": cid, "scene_order": i // 2,
                          "order": i, "status": "ready", "image_url": url,
                          "bubbles": [{"id": "b", "text": "Some dialogue line here for wrapping test",
                                       "type": "speech", "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.15}]})

t = time.time()
r = requests.get(f"{API}/chapters/{cid}/export/pdf", timeout=180)
dur = time.time() - t
print(f"status={r.status_code} secs={dur:.1f} size_kb={len(r.content)//1024} ct={r.headers.get('content-type')}")
print("cd:", r.headers.get("content-disposition"))

for col in ("chapters", "panels", "scenes", "generation_jobs"):
    db[col].delete_many({"manga_id": mid})
db.mangas.delete_many({"client_id": TAG})
print("cleaned")
