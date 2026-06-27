<div align="center">

# 🥜 NUTSHELL

### The news, cracked open and summarized — your way.

**An AI-powered news ecosystem that reads the internet so you don't have to.**
Live RSS + NewsAPI ingestion, Gemini-generated summaries tuned to *your* reading level,
a gamified quiz-and-leaderboard loop, and an interactive 3D globe of world headlines —
all wrapped in a neo-zine brutalist interface.

[![Next.js](https://img.shields.io/badge/Next.js-14-000000?logo=next.js)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#-license)

**NutShell ships as two repos:** 🎨 [NEWS-AI](https://github.com/achal2005/NEWS-AI) (frontend, on Vercel) · ⚙️ [NEWS-AI-BACKEND](https://github.com/achal2005/NEWS-AI-BACKEND) (backend, on Render)

</div>

---

## Why this exists

The modern news experience is broken in two directions at once: it's either an infinite
doomscroll that respects none of your time, or a paywalled wall of jargon that assumes a
finance degree. NutShell is my answer to both.

It ingests real news from 45+ live sources, then uses Google's Gemini to rewrite each story
at a complexity level *you* choose — anywhere from "explain it like I'm in 5th grade" to
"give me the post-grad analyst brief." Then it makes staying informed genuinely fun: read
articles to earn points, take a weekly quiz generated from the actual news, and climb a
live leaderboard. Spin the globe to see what the world is reading right now.

No localStorage tokens. No XSS-able auth. No "summary" that's just the first paragraph
copy-pasted. It's the news app I actually wanted to use.

---

## ✨ Features

🧠 **Depth-calibrated AI summaries** — Pick a complexity from **1 to 10**. Gemini treats it
as a continuous gradient, not three canned presets — a level 4 is genuinely distinct from a
level 5. Two formats: *Skim* (3 punchy bullets) and *Deep* (a Bloomberg-style brief).

📰 **Real, full-text news** — NewsAPI + 45+ RSS feeds across 8 categories. The free tiers
truncate articles, so NutShell scrapes the full body itself (with SSRF protection) before
summarizing — no "[+2400 chars]" cop-outs.

🎮 **Gamified reading** — Earn points for genuine reading time, take an AI-generated weekly
quiz built from the week's stories, and compete on a live weekly leaderboard.

🌍 **Interactive 3D globe** — A three.js globe of the planet; click any country to pull its
top headlines straight from Google News in that country's locale.

💬 **Chat with the editor** — Ask follow-up questions about any article. The article is
pinned as *data, not instructions*, with prompt-injection sanitization on both sides.

🔐 **Genuinely secure auth** — Passwordless Google OAuth with full ID-token signature
verification. The JWT lives **only** in an HttpOnly cookie — never in localStorage, never in
a JSON body, never readable by JavaScript.

🎨 **A UI with a point of view** — Neo-zine brutalist design: heavy type, a film-grain noise
overlay, Framer Motion throughout, dark/light themes. Opinionated on purpose.

---

## 🏗️ How it works

```
                          ┌──────────────────────────────┐
   RSS x45  ─┐            │        FastAPI Backend        │
   NewsAPI  ─┼──ingest──▶ │  • URL-normalize + SHA-256    │
             │            │    dedup                      │
             │            │  • APScheduler (6h refresh,   │
             │            │    2h reconcile, 15m board)   │            ┌─────────────┐
             │            │  • Gemini 2.5 Flash service   │ ◀── on ──▶ │   Gemini    │
             │            │    (rate-limit + circuit      │   demand   │  2.5 Flash  │
             │            │     breaker + retry)          │            └─────────────┘
             │            │  • Google OAuth → JWT cookie  │
             │            └───────────────┬──────────────┘
   (Kafka,   │                            │ JSON over HTTPS
   optional) ┘                            │ (HttpOnly cookie auth)
                                          ▼
                          ┌──────────────────────────────┐
                          │      Next.js 14 Frontend      │
                          │  • App Router + React Query   │
                          │  • Edge middleware gating     │
                          │  • three.js globe, Framer     │
                          └──────────────────────────────┘
```

A few design decisions I'm proud of:

- **URL-normalized dedup** — tracking params stripped, scheme/host normalized, then SHA-256
  hashed, so the same story from five places counts once.
- **Race-safe summary caching** — Postgres `ON CONFLICT DO NOTHING` with a SQLite
  `IntegrityError` fallback, keyed on `(article_id, mode, depth_level)`.
- **Atomic counters** — reading time and article counts use `UPDATE col = col + n`, so two
  open tabs can't clobber each other.
- **Per-concern circuit breakers** — a Gemini hiccup in summaries won't take down chat.

---

## 🧰 Tech stack

| Layer | Tools |
|-------|-------|
| **Frontend** | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, Framer Motion, TanStack Query, Zustand, three.js / react-three-fiber |
| **Backend** | FastAPI, SQLAlchemy 2.x, Pydantic v2, APScheduler, slowapi, BeautifulSoup, feedparser, httpx |
| **AI** | Google Gemini 2.5 Flash |
| **Data** | SQLite (local) · PostgreSQL + psycopg v3 (prod) |
| **Auth** | Google OAuth 2.0 → JWT in HttpOnly cookies |
| **Infra** | Render (backend) · Vercel (frontend) · Kafka (optional) |

---

## 🚀 Quickstart

**Prerequisites:** Python 3.11+ (3.14 tested), Node 18+, a Google OAuth client, and a
Gemini API key. A NewsAPI key is optional — RSS works without it.

### 1. Backend — [NEWS-AI-BACKEND](https://github.com/achal2005/NEWS-AI-BACKEND)

```bash
git clone https://github.com/achal2005/NEWS-AI-BACKEND.git
cd NEWS-AI-BACKEND
python -m venv venv
# Windows:  .\venv\Scripts\activate     macOS/Linux:  source venv/bin/activate
pip install -r requirements.txt

# Create backend/.env from the example, then fill in your keys
cp .env.example .env

uvicorn app.main:app --reload --port 8000
```

Backend is now live at **http://localhost:8000** — interactive API docs at `/docs`.

### 2. Frontend — [NEWS-AI](https://github.com/achal2005/NEWS-AI)

```bash
git clone https://github.com/achal2005/NEWS-AI.git
cd NEWS-AI
npm install
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Open **http://localhost:3000** and you're in.

> 💡 Run the backend and frontend in two terminals (backend first, so the API is up).

---

## 🔑 Environment variables

**Backend (`backend/.env`)**

| Variable | Required | Notes |
|----------|:--------:|-------|
| `JWT_SECRET_KEY` | ✅ | ≥ 32 chars. The app refuses to boot in prod with a known dev default. |
| `DATABASE_URL` | ✅ | `sqlite:///./news_db.sqlite` locally, or a Postgres URL in prod. |
| `GEMINI_API_KEY` | ✅ | From Google AI Studio. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | ✅ | Google OAuth credentials. |
| `NEWS_API_KEY` | — | Optional; RSS feeds work without it. |
| `ENVIRONMENT` / `DEBUG` / `DEV_LOGIN_ENABLED` | — | Dev conveniences (dev-login is triple-guarded). |
| `KAFKA_BOOTSTRAP_SERVERS` / `RENDER_EXTERNAL_URL` | — | Optional queue + keep-alive ping. |

**Frontend (`frontend/.env.local`)**

| Variable | Notes |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | Backend base URL (e.g. `http://localhost:8000`). |
| `NEXT_PUBLIC_SITE_URL` | Optional; canonical site URL for OG metadata. |

> ⚠️ `.env` files are gitignored and **must never be committed** — they hold live secrets.

---

## 📁 Project structure

**Backend** — [`NEWS-AI-BACKEND`](https://github.com/achal2005/NEWS-AI-BACKEND)

```
app/
├── main.py          App + lifespan (migrations, scheduler, keep-alive)
├── api/             auth · news · gamification · user routers
├── core/            config · security · cache · scheduler · limiter
├── db/              SQLAlchemy models + session
└── services/        gemini · oauth · newsapi · rss · scraper · kafka
```

**Frontend** — [`NEWS-AI`](https://github.com/achal2005/NEWS-AI)

```
app/                 routes (dashboard, article, quiz, globe, ...)
components/          UI + globe scene
lib/                 auth context
middleware.ts        edge auth gating
```

New here? **`brain.md`** (in each repo) is a one-page map of the whole codebase.

---

## 🛡️ Security highlights

- JWT only ever in an HttpOnly cookie — zero JS-accessible token surface.
- Full Google ID-token **signature** verification (not just decode).
- SSRF guard on all server-side fetches (private/loopback IPs rejected, size + time caps).
- Prompt-injection sanitization + a structural data/instruction boundary for AI chat.
- Rate limiting on auth and refresh endpoints (slowapi) plus per-user Gemini token buckets.
- CSP without `unsafe-eval`, bcrypt(12) password hashing, strict CORS allow-list.

---

## ☁️ Deployment

- **Backend → Render:** `render.yaml` + `Dockerfile` + `build.sh`. Auto-rewrites
  `postgres://` URLs for psycopg v3, runs a tuned connection pool, and self-pings every
  14 min to dodge free-tier cold starts.
- **Frontend → Vercel:** `output: 'standalone'`, CSP headers, and cross-origin
  `SameSite=none; Secure` cookies wired up in `next.config.js`.

---

## 🗺️ Roadmap

- [ ] Migrate from the EOL `google-generativeai` SDK to `google-genai`
- [ ] Redis-backed caching for multi-instance scale-out
- [ ] Push notifications for breaking news in followed categories
- [ ] Saved articles / read-later
- [ ] Automated test suite (pytest + Playwright)

---

## 📝 License

MIT — see [LICENSE](LICENSE). Use it, fork it, learn from it.

<div align="center">

**Built with curiosity, caffeine, and a refusal to read another truncated summary.**

</div>
