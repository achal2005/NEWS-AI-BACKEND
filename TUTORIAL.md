# 🛠️ Tutorial: Build the AI News Ecosystem from Scratch

Welcome! This tutorial is structured for beginners. We will walk through the exact steps taken to build this project from an empty folder into a fully functioning AI-powered web application.

By the end of this guide, you will understand how to connect a React/Next.js frontend to a Python/FastAPI backend, and how to use Google's Gemini AI to make applications smart!

---

## Phase 1: Planning and Setup

Every great project starts with a plan. We needed:
1. A place to store data (Database).
2. A brain to process logic and talk to AI (Backend Server).
3. A beautiful face for users to interact with (Frontend Website).

### Step 1: Folder Structure
We create a main folder called `news project`, and inside it, two folders: `backend` and `frontend`. Keeping them separate keeps our code clean!

---

## Phase 2: Building the Backend (Python + FastAPI)

The backend is like a restaurant kitchen. The users (frontend) send "orders" (requests), and the backend prepares the "food" (data) and sends it back.

### Step 2: Setting up FastAPI
Inside the `backend` folder, we initialize a Python virtual environment to keep our packages isolated.
We install `fastapi` and `uvicorn` (the server runner).

We create `app/main.py`. This is the entry point.
```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def read_root():
    return {"status": "healthy"}
```
Just like that, we have a running server!

### Step 3: Setting up the Database (SQLAlchemy)
We need a place to store Articles and Users. We use **SQLite** (a lightweight file-based database) and **SQLAlchemy** (a tool that lets us write Python instead of raw SQL code).

We create `app/db/models.py` and define our tables:
```python
class Article(Base):
    __tablename__ = "articles"
    id = Column(String, primary_key=True)
    title = Column(String)
    url = Column(String)
```

### Step 4: Fetching the News
We need actual news. We created an account on **NewsAPI.org** to get an API key.
We create a service `app/services/news_api.py`. It sends an HTTP request to NewsAPI, gets a list of JSON articles, and saves them to our SQLite database using the models we just made.

### Step 5: Integrating Google Gemini AI 🧠
This is the magic part! We install the `google-generativeai` package.
In `app/services/gemini.py`, we write a function that takes an article's text, adds a prompt, and sends it to Gemini.

```python
import google.generativeai as genai

def generate_summary(text: str, mode: str):
    if mode == "kid":
        prompt = f"Summarize this for a 10 year old using emojis: {text}"
    else:
        prompt = f"Give a professional executive brief: {text}"
        
    response = genai.GenerativeModel("gemini-2.5-flash").generate_content(prompt)
    return response.text
```

### Step 6: Creating API Endpoints
We link our services to URLs so the frontend can use them. In `app/api/news.py`, we create:
- `GET /api/news` -> Returns the list of articles from the database.
- `GET /api/news/{id}/summary?mode=kid` -> Calls our Gemini function and returns the AI summary.

---

## Phase 3: Building the Frontend (Next.js + React)

Now we move to the `frontend` folder. We use `npx create-next-app@latest` to bootstrap our website.

### Step 7: The Landing Page and Animations
We want a "wow" factor. We use **Tailwind CSS** for easy styling and install **Framer Motion** for animations.
In `app/(landing)/page.tsx`, we create the big hero text ("THE DAILY BRIEF"). We attach Framer Motion's `useScroll` hook to make the text fade out naturally as the user scrolls down.

### Step 8: The Dashboard (Fetching Data)
The user goes to the dashboard. We need to display the news from our backend.
In `app/dashboard/page.tsx`, we use React's `useEffect` hook to "fetch" data when the page loads.

```javascript
useEffect(() => {
    fetch("http://localhost:8000/api/news")
        .then(response => response.json())
        .then(data => setArticles(data));
}, []);
```
We take that `data` and map it into beautiful `ArticleCard` components that we designed using Tailwind.

### Step 9: The Article Page & Reading Timer
When a user clicks an article, they land on `app/article/[id]/page.tsx`.
They can click a toggle button to switch between "Kid" and "Pro" modes. Clicking the button "fetches" the summary from our backend endpoint we made in Step 6!

**Gamification:** We want to reward them for reading. We use `setInterval` to count the seconds they spend on the page. When they click the "Back" button (or unmount the component), we send a fast HTTP POST request to the backend: *"Add 10 points to this user!"*

### Step 10: Generating Quizzes Automatically
To make the learning stick, we added a quiz. 
On the backend (`app/api/gamification.py`), we wrote an endpoint that grabs the 5 most recent articles, glues their text together, and asks Gemini: *"Generate a 10-question JSON quiz based on this text."*
The frontend calls this endpoint, gets the JSON questions, and renders interactive buttons. When the user clicks the right answer, their score goes up!

---

## Phase 4: Tying it all together

### Step 11: CORS (Cross-Origin Resource Sharing)
Initially, the frontend (port 3000) could not talk to the backend (port 8000) because browsers block it for security.
In our backend `main.py`, we added the `CORSMiddleware` and told it: *"Allow requests coming from localhost:3000!"*

### Step 12: Polish and Fixing Bugs
We spent time adjusting fonts, adding smooth transitions, handling "Loading" states (showing spinners while Gemini is thinking), and writing a `start_project.ps1` script so users can easily launch everything at once.

---

## 🎉 Conclusion

Building this project taught us:
1. How to build APIs using **FastAPI**.
2. How to talk to LLMs (Large Language Models) using **Google Gemini**.
3. How to build beautiful, animated user interfaces using **Next.js** and **Framer Motion**.
4. How to gamify a workflow using timers and points.

Feel free to explore the codebase. Start in `backend/app/main.py` and `frontend/app/page.tsx`, and trace the logic step-by-step!
