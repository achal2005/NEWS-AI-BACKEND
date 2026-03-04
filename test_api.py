import os
import sys

# Add backend directory to sys.path to import app modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.db import SessionLocal, User
from app.core.security import create_access_token

def get_test_token():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            print("No users in DB. Creating a mock user...")
            user = User(
                email="test@example.com",
                display_name="Test User",
                profile_complete=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        
        token = create_access_token({"sub": str(user.id)})
        return token
    finally:
        db.close()

import requests

def test_summary():
    print("Getting token...")
    token = get_test_token()
    print("Fetching news listing...")
    res = requests.get('http://127.0.0.1:8000/api/news')
    res.raise_for_status()
    items = res.json().get('items', [])
    if not items:
        print("No articles found to summarize.")
        return
    
    first_id = items[0]['id']
    print(f"Requesting summary for Article ID {first_id}...")
    
    headers = {"Authorization": f"Bearer {token}"}
    for mode in ["kid", "pro"]:
        print(f"  -> Mode: {mode}")
        s_res = requests.get(f'http://127.0.0.1:8000/api/news/{first_id}/summary?mode={mode}', headers=headers)
        if s_res.status_code == 200:
            print(f"     SUCCESS. Summary length: {len(s_res.json().get('summary', ''))}")
        else:
            print(f"     FAILED. Status: {s_res.status_code}, Detail: {s_res.text}")

if __name__ == '__main__':
    test_summary()
