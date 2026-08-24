# AI Manga Studio — PRD

## Original Problem Statement (Turkish, verbatim excerpt)
AI Manga Studio — Web App (React + FastAPI + MongoDB). Kullanıcı yalnızca fikir verir; sistem hikaye planını hemen, bölümleri ve görselleri talep üzerine aşamalı üretir. Konuşma balonları frontend'de SVG overlay olarak eklenir ve düzenlenebilir. 100 bölüme kadar destek, ama sadece story bible + chapter outline hemen üretilir; bölümler talep üzerine üretilir. Karakter tutarlılığı: Gemini Nano Banana reference-image editing. Auth: MVP anonim client_id (localStorage UUID). Background jobs: FastAPI async worker + MongoDB state machine. SSE progress. AI keys env-only.

## Architecture Delivered
- Backend: FastAPI + Motor (MongoDB), async job queue via asyncio + Mongo `generation_jobs` collection with SSE progress.
- AI: Claude Sonnet 4.6 (primary text) + Gemini 3 Flash (fallback) via Emergent LLM Key + Gemini Nano Banana (image gen with reference images).
- Storage: Emergent Object Storage (S3-compatible) for character portraits and panel images.
- Frontend: React 19 (JSX) + Tailwind + Framer Motion + shadcn/ui + sonner + zustand.

## User Personas
- Solo creator with a story idea but no drawing skill.
- Anonymous — no auth required; localStorage UUID pins a library to a device.

## Core Requirements (static)
1. Instant story plan (title, logline, synopsis, world, characters, chapter outline).
2. On-demand chapter/panel generation with progress.
3. Character reference-image consistency (AI portrait or user upload).
4. Editable SVG dialogue bubble overlay.
5. Publish to Explore feed.

## What's Been Implemented (2026-02, MVP first cut)
- Async POST /api/mangas returning job_id (was blocking ≥60s — fixed).
- Story plan pipeline: Claude JSON → world/characters/chapters/story_memory persisted.
- Character portrait generation via Nano Banana + user upload override.
- Chapter generation job: scene decomposition → panels → Nano Banana panel images with character references → auto-computed bubble positions.
- Reader with vertical scroll + inline editable SVG bubbles (speech/thought/shout/whisper/narration/SFX).
- Library, Explore, Settings pages.
- Live SSE progress at /api/jobs/{id}/stream.
- Input validation (idea min 8 chars, chapter_count 1-20), 404 on unknown ids, sanitized AI errors (no cost/budget leak), non-blocking storage via asyncio.to_thread, startup reconciliation for interrupted jobs, task registry to prevent GC.

## Testing Status
- Backend: 19/19 full-pipeline tests passed (Claude → Nano Banana → storage → reader). Structural fixes verified by curl (async create <200ms, validation 422, 404s work, error sanitization works).
- AI budget was exhausted during exhaustive first test. User must top up Emergent Universal Key to run full pipeline.

## P0 Backlog (Phase 5-8)
- Duplicate manga action in Library.
- PDF export with baked bubbles (Pillow composite) + ZIP + text export.
- Bookmark / continue-reading state in Reader.
- Admin Settings page: cap panels per chapter (control cost), default style, retry count.

## P1 Backlog
- Ownership guard: client_id checks on rename/publish/delete/generate.
- Bookmark storage + last-read chapter tracking.
- Chapter batch generation ("Generate Chapters 1-5").
- Bubble drag/resize handles + shape switcher UI.

## P2 Backlog
- Real auth (JWT / Emergent Google Auth).
- Community moderation for Explore.
- Push to fully-managed job queue (Celery + Redis) when scale > 1 pod.
