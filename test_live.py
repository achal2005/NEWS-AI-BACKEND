"""Quick diagnostic script for live deployment."""
import httpx
import json

base = "https://daily-brief-api.onrender.com"

print("=== 1. Root Health ===")
try:
    r = httpx.get(f"{base}/", timeout=60)
    print(f"  Status: {r.status_code} -> {r.json()}")
except Exception as e:
    print(f"  FAILED: {e}")

print("\n=== 2. Auth Google URL ===")
try:
    r = httpx.get(f"{base}/api/auth/google", timeout=30)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        url = r.json()["auth_url"]
        for p in url.split("&"):
            if "redirect" in p.lower():
                print(f"  redirect_uri: {p}")
except Exception as e:
    print(f"  FAILED: {e}")

print("\n=== 3. News API ===")
try:
    r = httpx.get(f"{base}/api/news?page=1&page_size=3", timeout=60)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        keys = list(data.keys())
        print(f"  Response keys: {keys}")
        articles = data.get("articles", data.get("items", []))
        print(f"  Article count: {len(articles)}")
        if articles:
            a = articles[0]
            print(f"  First article: {a.get('title', 'N/A')[:80]}")
    else:
        print(f"  Body: {r.text[:300]}")
except Exception as e:
    print(f"  FAILED: {e}")

print("\n=== 4. CORS Preflight ===")
try:
    r = httpx.options(f"{base}/api/news", headers={
        "Origin": "https://news-ai-wine.vercel.app",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "content-type",
    }, timeout=30)
    print(f"  Status: {r.status_code}")
    for k, v in r.headers.items():
        if "access-control" in k.lower():
            print(f"  {k}: {v}")
except Exception as e:
    print(f"  FAILED: {e}")

print("\n=== 5. Quiz List ===")
try:
    r = httpx.get(f"{base}/api/quiz/list", timeout=30)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Quizzes: {len(data) if isinstance(data, list) else data}")
    else:
        print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  FAILED: {e}")

print("\n=== 6. Leaderboard ===")
try:
    r = httpx.get(f"{base}/api/leaderboard", timeout=30)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Entries: {len(data) if isinstance(data, list) else list(data.keys())[:5]}")
    else:
        print(f"  Body: {r.text[:200]}")
except Exception as e:
    print(f"  FAILED: {e}")

print("\nDone!")
