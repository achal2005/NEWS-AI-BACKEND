# brain.md — Fast Repo Index for NutShell (AI News Ecosystem)

> Purpose: a compact map so an assistant can answer questions without re-reading the
> whole tree. For exhaustive detail see `PROJECT_CONTEXT_FOR_REVIEW.md`.
> Last verified: 2026-06-27.

## What it is
Full-stack AI news aggregator. FastAPI backend + Next.js 14 frontend. Pulls news
(NewsAPI + 45 RSS feeds), generates Gemini summaries (kid/pro × depth 1-10), gamifies
reading (points, weekly quiz, leaderboard). Google OAuth → JWT in HttpOnly cookie.

## Stack & runtime
- **Backend**: Python **3.14** (venv at `backend/venv`), FastAPI, SQLAlchemy 2.x,
  SQLite local / Postgres (psycopg v3) prod. Entry: `backend/app/main.py`.
- **Frontend**: Next.js 14.1 App Router, React 18, TS, Tailwind, Framer Motion,
  React Query, Zustand, three.js (globe). Entry: `frontend/app/page.tsx`.
- **AI**: Google Gemini `gemini-2.5-flash` via `google-generativeai` (deprecated SDK — see Tech debt).
- **Run**: `start.bat` / `start_project.ps1` → uvicorn :8000 + `npm run dev` :3000.
- **Deploy**: backend on Render (`render.yaml`, `build.sh`, `Dockerfile`), frontend on Vercel.

## Backend file map (`backend/app/`)
- `main.py` — app, lifespan (JWT guard, table create, depth_level auto-migrate, Kafka,
  scheduler, Render keep-alive ping), CORS, router mount, `/` + `/health`.
- `core/config.py` — pydantic-settings `Settings`; `.env` loaded via `_find_env_file()`;
  `extra="ignore"`; JWT secret ≥32 chars validator; `_DEV_DEFAULT_SECRETS` guard.
- `core/security.py` — JWT create/decode, bcrypt(12), `get_current_user_id` (required),
  `get_optional_user_id` (None if no token, **401 if invalid**). Token from cookie `auth_token` first, then Bearer.
- `core/limiter.py` — slowapi `Limiter(key_func=get_remote_address)` singleton.
- `core/cache.py` — `TTLCache` (thread-safe, max-entry eviction). `article_list_cache`(50), `summary_cache`(100, currently only referenced in /health).
- `core/scheduler.py` — APScheduler jobs: news refresh 6h + 60s-after-boot,
  reconcile missing summaries 2h, leaderboard cache 15m.
- `core/time_utils.py` — `get_current_week_start/end` (Mon 00:00 UTC, tz-aware).
- `db/session.py` — engine (postgres:// → postgresql+psycopg://), `SessionLocal`, `get_db`, `Base`.
- `db/models.py` — 11 models. Key unique constraints: Article.url_hash,
  ArticleSummary(article_id,mode,depth_level), PointsLedger(user_id,action_type,reference_id),
  WeeklyQuiz.week_start.
- `schemas/__init__.py` — all Pydantic request/response models.
- `api/auth.py` — `/api/auth`: google url/callback, complete-profile, me, logout, dev-login (triple-guarded).
- `api/news.py` — `/api/news`: list (cached 5m), refresh (5/h), refresh-rss (2/h, auth),
  categories, get/summary/regenerate-summary/chat, create. URL normalize+SHA256 dedup, race-safe summary upsert.
- `api/gamification.py` — `/api`: points, reading-time (atomic+dedup award), leaderboard,
  quiz weekly/list/{id}/generate/submit. Lock-then-generate for quiz.
- `api/user.py` — `/api/user/profile` GET/PUT (taste profile + depth_preference).
- `services/gemini.py` — `GeminiService` singleton: token-bucket RPM limiter (global 15,
  user 5, anon 3, LRU 500), per-concern circuit breakers (5 fail → 60s), retry w/ backoff,
  `_parse_json_list` validation (raises `GeminiParseError`), prompt-injection sanitizers, multi-turn chat.
- `services/google_oauth.py` — code exchange + ID-token signature verify + userinfo fallback.
- `services/news_api.py` — NewsAPI client + scrape + paywall/category inference.
- `services/rss_aggregator.py` — 45+ feeds, `asyncio.Semaphore(10)`, feedparser in executor.
- `services/article_scraper.py` — full-text scrape with SSRF guard (`is_safe_url`), 512KB/10s caps.
- `services/kafka_service.py` — optional producer/consumer (app works without Kafka).
- `services/ai_consumer.py` — Kafka consumer: dual summaries + jargon; health on :8001; `asyncio.run` entry.

## Frontend file map (`frontend/`)
- `middleware.ts` — edge gating; checks **flag** cookie `token` only (HttpOnly JWT not visible cross-domain).
- `lib/auth.tsx` — `AuthProvider`, `useAuth`, `withAuth`; all fetches `credentials:'include'`;
  sets non-sensitive `token=authenticated` flag cookie; real JWT stays in backend HttpOnly cookie.
- `app/layout.tsx` — providers: Auth → Query → Theme → LayoutShell → ErrorBoundary.
- `app/page.tsx` landing; `dashboard`, `article/[id]`, `quiz`, `leaderboard`, `profile`,
  `onboarding`, `login`, `register`, `privacy`, `terms`, `globe`, `auth/callback`.
- `app/api/globe-news/route.ts` — proxies Google News RSS per country (globe feature, self-contained).
- `components/ui/` — ArticleCard, Sidebar, NewsTicker, Globe/{GlobeScene,CountryNewsPanel}, etc.

## Auth flow (key invariant)
JWT is **only** ever in the backend-set HttpOnly `auth_token` cookie — never in JSON body,
localStorage, or JS-readable cookie. Frontend sets a separate `token=authenticated` flag
cookie purely for edge middleware. Cross-origin cookie = `SameSite=none; Secure` (prod);
dev-login uses `SameSite=lax; Secure=false`.

## Env vars
Required: `JWT_SECRET_KEY`(≥32), `DATABASE_URL`, `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`.
Optional: `NEWS_API_KEY`, `KAFKA_BOOTSTRAP_SERVERS`, `FRONTEND_URL`, `DEBUG`, `ENVIRONMENT`,
`DEV_LOGIN_ENABLED`, `RENDER_EXTERNAL_URL`, frontend `NEXT_PUBLIC_API_URL`.
Note: `ENVIRONMENT`/`DEV_LOGIN_ENABLED` are now real `Settings` fields (read via `settings.*`).

## Conventions / gotchas
- Modes: API takes `kid|pro|skim|deep`; `kid→skim`, `pro→deep` normalized before caching.
- Summaries cached in DB by `(article_id, mode, depth_level)`, race-safe upsert
  (PG `on_conflict_do_nothing`, SQLite IntegrityError fallback).
- Points dedup via unique `(user_id, action_type, reference_id)` + IntegrityError catch.
- Counters (`reading_time`, `articles_read`) use atomic `UPDATE col=col+N`, not read-modify-write.
- Caches are in-process only (single instance); swap for Redis if scaling out.
- Rate limits: slowapi decorators on auth + news refresh endpoints; Gemini has its own token buckets.

## Verify commands
- Backend compile: `backend/venv/Scripts/python.exe -m compileall -q app`
- Backend import smoke: `backend/venv/Scripts/python.exe -c "import app.main"`
- Frontend typecheck: `cd frontend && npx tsc --noEmit`

## Tech debt / known non-blocking issues
- `google.generativeai` SDK is EOL (emits FutureWarning) → migrate to `google.genai`.
- `summary_cache` (core/cache.py) is created but only read by `/health`; never populated.
- `middleware.ts` has a JWT-expiry decode block that never runs (flag cookie isn't a JWT) — harmless dead code.
- `get_article_summary` has an `article.url` branch; model only has `source_url` — dead branch.

## Fixes applied 2026-06-27 (this session)
1. **Startup crash**: `.env` had `DEV_LOGIN_ENABLED`/`ENVIRONMENT` not declared in `Settings`
   → pydantic-settings v2 rejected unknown keys. Added both as fields + `extra="ignore"`.
2. **Dev-login flag ignored**: `auth.py`/`main.py` read those flags from `os.environ`
   (never populated from `.env`) → now read via `settings.*`. Removed unused `import os` in auth.py.
3. **Missing rate limiting**: `/api/news/refresh` & `/refresh-rss` documented limits but had no
   `@limiter.limit` decorator (only an unused local). Added `@limiter.limit("5/hour")` / `("2/hour")`;
   removed dead `_get_limiter` helper.
4. **Deprecated asyncio**: `asyncio.get_event_loop().create_task(...)` → `asyncio.create_task(...)` in `_store_article`.
5. **Missing dependency**: installed `slowapi` (in requirements.txt but absent from venv) — app couldn't boot.
