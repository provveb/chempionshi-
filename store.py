"""
store.py — Turnir ma'lumotlarini JSON faylda saqlash qatlami.

sqlite o'rniga: barcha ma'lumot bitta data.json faylida saqlanadi.
Har bir yozish (save) operatsiyasidan keyin fayl avtomatik ravishda
GitHub repo'ga commit qilinadi (github_sync.py orqali), shunda Render
auto-deploy ishlab, eng so'nggi holat doimiy saqlanadi.
"""

from __future__ import annotations

import json
import os
import threading

from github_sync import push_to_github

DATA_DIR = os.environ.get("DB_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "data.json")

# Eslatma: DATA_FILE — runtime'da (Render diskida) yoziladigan fayl yo'li.
# GitHub'ga push qilinganda esa repo ichidagi fayl nomi github_sync.GITHUB_DATA_PATH
# orqali boshqariladi (ular alohida narsalar).

_lock = threading.RLock()

DEFAULT_DATA = {
    "settings": {
        "name": "CS2 UZ Championship",
        "max_teams": "16",
        "max_players_per_team": "6",
        "status": "registration",
        "prize_pool": "$500",
        "rules": "MR12, 5v5, Standard CS2 qoidalari.",
        "stage": "Guruh bosqichi",
    },
    "admin": {
        "username": "pro_vveb",
        # parolni o'zgartirish: Render env-o'zgaruvchisi ADMIN_PASSWORD orqali
        "password_hash": "__SET_ON_FIRST_RUN__",
    },
    "teams": [],
    "players": [],
    "matches": [],
    "next_ids": {"team": 1, "player": 1, "match": 1},
}


def _seed_admin_hash(data: dict) -> dict:
    import hashlib
    if data["admin"]["password_hash"] == "__SET_ON_FIRST_RUN__":
        default_pw = os.environ.get("ADMIN_PASSWORD", "slx12344")
        data["admin"]["password_hash"] = hashlib.sha256(default_pw.encode()).hexdigest()
    return data


def _write_local(data: dict) -> None:
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def init_store() -> None:
    """Fayl mavjud bo'lmasa, standart ma'lumotlar bilan yaratadi; bo'lsa, yangi maydonlarni qo'shadi."""
    with _lock:
        if not os.path.exists(DATA_FILE):
            data = _seed_admin_hash(json.loads(json.dumps(DEFAULT_DATA)))
            _write_local(data)
            return
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for key, val in DEFAULT_DATA.items():
            if key not in data:
                data[key] = val
                changed = True
        data = _seed_admin_hash(data)
        if changed:
            _write_local(data)


def load() -> dict:
    with _lock:
        if not os.path.exists(DATA_FILE):
            init_store()
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)


def save(data: dict, commit_message: str = "Update tournament data") -> None:
    """Mahalliy faylga yozadi, so'ng GitHub'ga commit qiladi (sozlangan bo'lsa)."""
    with _lock:
        _write_local(data)
    push_to_github(DATA_FILE, commit_message)


def next_id(data: dict, kind: str) -> int:
    nid = data["next_ids"].get(kind, 1)
    data["next_ids"][kind] = nid + 1
    return nid
