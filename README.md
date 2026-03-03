# The Daily Brief (AI News Ecosystem)

A full-stack, AI-powered personalized news aggregation platform. "The Daily Brief" automatically ingests live RSS feeds, processes the articles using Google's Gemini AI to generate customized summaries, and presents them in a beautiful, newspaper-style UI with gamified engagement features.

## ✨ Features

*   **Automated News Ingestion:** A python job scheduler fetches, parses, and deduplicates news from various RSS sources.
*   **AI-Powered Summaries:** Integrates with Google Gemini API to dynamically generate "Pro Analyst" (deep dives) or "Student" (simplified) summaries based on the user's reading preference.
*   **Secure Authentication:** Passwordless Google OAuth 2.0 implementation with JWT session management.
*   **Gamification:** Interactive daily quizzes generated from the day's news, global leaderboards, and user leveling systems.
*   **Modern Newspaper UI:** Highly responsive CSS masonry/grid design built with Next.js and Tailwind CSS, featuring smooth Framer Motion animations.
*   **Fully Deployed:** Frontend hosted on Vercel, Backend hosted on Render with a PostgreSQL database.

## 🛠️ Tech Stack

**Frontend:**
*   Next.js 14 (App Router)
*   React 18
*   Tailwind CSS
*   Zustand (State Management)
*   Tanstack React Query
*   Framer Motion
*   Lucide React (Icons)

**Backend:**
*   FastAPI (Python)
*   PostgreSQL & SQLAlchemy (ORM)
*   Alembic (Migrations)
*   Google Generative API (Gemini Pro)
*   APScheduler (Automated Jobs)
*   BeautifulSoup4 & Feedparser
*   Uvicorn

## 🚀 Getting Started

### Prerequisites
*   Node.js (v18+)
*   Python (3.10+)
*   PostgreSQL database
*   Google Cloud Console Account (for OAuth Client ID/Secret)
*   Google Gemini API Key

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/achal2005/NEWS-AI.git
    cd NEWS-AI
    ```

2.  **Backend Setup:**
    ```bash
    cd backend
    python -m venv venv
    source venv/bin/activate  # On Windows: .\venv\Scripts\activate
    pip install -r requirements.txt
    ```
    Create a `.env` file in the `backend` directory based on `.env.example` and fill in your database, JWT, Gemini, and Google OAuth credentials.

    Run database migrations and start the server:
    ```bash
    alembic upgrade head
    uvicorn app.main:app --reload --port 8000
    ```

3.  **Frontend Setup:**
    Open a new terminal window.
    ```bash
    cd frontend
    npm install
    ```
    Create a `.env.local` file in the `frontend` directory with:
    ```env
    NEXT_PUBLIC_API_URL=http://localhost:8000
    ```
    Start the development server:
    ```bash
    npm run dev
    ```

4.  **Open the application:**
    Navigate to `http://localhost:3000` in your browser.

## 🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the issues page.

## 📝 License
This project is open source and available under the [MIT License](LICENSE).
