"""
tournament.db faylini GitHub repo'siga avtomatik push qilish.

Kerakli environment variable'lar (Render'da o'rnatiladi):
  GITHUB_TOKEN  - Fine-grained Personal Access Token (Contents: Read and write)
  GITHUB_REPO   - masalan: "provveb/chempionshi"
  GITHUB_BRANCH - masalan: "main" (ixtiyoriy, default "main")
  DB_PATH_IN_REPO - repo ichidagi fayl yo'li, masalan "tournament.db" (ixtiyoriy)
"""
import os
import base64
import threading
import time
import requests

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'provveb/chempionshi')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')
DB_PATH_IN_REPO = os.environ.get('DB_PATH_IN_REPO', 'tournament.db')
LOCAL_DB_PATH = 'tournament.db'

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_PATH_IN_REPO}"

_dirty = False
_lock = threading.Lock()
_DEBOUNCE_SECONDS = 20  # tez-tez push qilavermaslik uchun kutish vaqti


def mark_dirty():
    """Baza o'zgartirilganda chaqiriladi (after_request orqali)."""
    global _dirty
    with _lock:
        _dirty = True


def _get_remote_sha():
    """Faylning GitHub'dagi joriy sha'sini olish (update uchun shart)."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.get(f"{API_URL}?ref={GITHUB_BRANCH}", headers=headers, timeout=15)
    if resp.status_code == 200:
        return resp.json().get('sha')
    return None  # fayl hali repo'da yo'q bo'lishi ham mumkin


def push_db_to_github():
    """tournament.db faylini GitHub'ga push qiladi (commit yaratadi)."""
    if not GITHUB_TOKEN:
        print("⚠️ GITHUB_TOKEN o'rnatilmagan, push o'tkazib yuborildi")
        return False
    if not os.path.exists(LOCAL_DB_PATH):
        print("⚠️ tournament.db topilmadi")
        return False

    with open(LOCAL_DB_PATH, 'rb') as f:
        content_b64 = base64.b64encode(f.read()).decode('utf-8')

    sha = _get_remote_sha()
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "message": f"Avtomatik DB yangilanishi {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "content": content_b64,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(API_URL, headers=headers, json=payload, timeout=20)
    if resp.status_code in (200, 201):
        print("✅ tournament.db GitHub'ga push qilindi → Render auto-deploy boshlanadi")
        return True
    else:
        print(f"❌ GitHub push xatosi: {resp.status_code} {resp.text}")
        return False


def _background_worker():
    """Fon rejimida ishlaydi: 'dirty' bo'lsa, debounce vaqtidan keyin push qiladi."""
    global _dirty
    while True:
        time.sleep(_DEBOUNCE_SECONDS)
        with _lock:
            should_push = _dirty
            _dirty = False
        if should_push:
            push_db_to_github()


def start_background_sync():
    """Flask ilovasi ishga tushganda bir marta chaqiriladi."""
    if not GITHUB_TOKEN:
        print("⚠️ GITHUB_TOKEN topilmadi — GitHub sync o'chirilgan")
        return
    t = threading.Thread(target=_background_worker, daemon=True)
    t.start()
    print(f"🔄 GitHub auto-sync ishga tushdi (har {_DEBOUNCE_SECONDS}s tekshiradi)")
