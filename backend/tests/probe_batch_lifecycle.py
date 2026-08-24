"""Ad-hoc probe: batch job lifecycle when AI workers fail (exhausted key).
Not part of the regression suite assertions beyond structure; documents observed behavior.
"""
import time
import uuid

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

API = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
benv = dotenv_values("/app/backend/.env")
db = MongoClient(benv["MONGO_URL"])[benv["DB_NAME"]]

nid = lambda: uuid.uuid4().hex
TAG = "TEST_probe_" + nid()[:6]
mid = nid()
db.mangas.insert_one({"id": mid, "client_id": TAG, "title": TAG, "max_panels_per_chapter": 8,
                      "art_style": "Manga", "genre": "Fantasy", "creativity": "balanced",
                      "stats": {}, "is_published": False, "created_at": "2026-01-01"})
chs = []
for n in (1, 2):
    cid = nid()
    db.chapters.insert_one({"id": cid, "manga_id": mid, "number": n, "title": f"{TAG} c{n}",
                            "summary": "s", "status": "planned"})
    chs.append(cid)

r = requests.post(f"{API}/mangas/{mid}/chapters/batch-generate", json={"chapter_ids": chs}, timeout=60)
print("POST", r.status_code, r.json())
batch_id = r.json()["batch_id"]
jobs = [j["job_id"] for j in r.json()["jobs"]]

for _ in range(20):
    b = requests.get(f"{API}/jobs/{batch_id}", timeout=30).json()
    if b["status"] in ("done", "error"):
        break
    time.sleep(2)
print("BATCH:", {k: b.get(k) for k in ("status", "progress", "error", "type")})
for j in jobs:
    d = requests.get(f"{API}/jobs/{j}", timeout=30).json()
    print("CHILD:", d["status"], d["progress"], repr(d.get("error")))
print("CHAPTER STATUSES:", [db.chapters.find_one({"id": c})["status"] for c in chs])
print("MANGA STATS:", db.mangas.find_one({"id": mid}).get("stats"))

# cleanup
for col in ("chapters", "panels", "scenes", "generation_jobs", "characters"):
    db[col].delete_many({"manga_id": mid})
db.mangas.delete_many({"client_id": TAG})
print("cleaned:", db.mangas.count_documents({"client_id": TAG}))
