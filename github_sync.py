"""
github_sync.py — data.json faylini GitHub repo'ga avtomatik commit qiladi.

Kerakli environment-o'zgaruvchilar (Render → Environment bo'limida sozlanadi):
    GITHUB_TOKEN     — GitHub Personal Access Token (repo yozish huquqi bilan)
    GITHUB_REPO      — "username/repo-nomi" formatida
    GITHUB_BRANCH    — odatda "main" (default: main)
    GITHUB_DATA_PATH — repo ichidagi fayl yo'li (default: data.json)

Bu fayl commit qilinganda, agar Render'da "Auto-Deploy" yoqilgan bo'lsa,
Render avtomatik ravishda qayta deploy qiladi va saytdagi ma'lumotlar yangilanadi.
"""

import os
import base64
import logging

import requests

log = logging.getLogger("github_sync")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")          # masalan: "samir/cs2-tournament"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_DATA_PATH = os.environ.get("GITHUB_DATA_PATH", "data.json")

API_URL = "https://api.github.com/repos/{repo}/contents/{path}"


def is_configured() -> bool:
    return bool(GITHUB_TOKEN and GITHUB_REPO)


def push_to_github(local_file_path: str, message: str = "Update tournament data") -> bool:
    """Mahalliy faylni o'qiydi va GitHub'dagi shu fayl bilan almashtiradi (commit qiladi)."""
    if not is_configured():
        log.warning("GITHUB_TOKEN yoki GITHUB_REPO sozlanmagan — GitHub sinxronizatsiya o'tkazib yuborildi")
        return False

    with open(local_file_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("utf-8")

    url = API_URL.format(repo=GITHUB_REPO, path=GITHUB_DATA_PATH)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    try:
        # Avval mavjud faylning sha'sini olamiz (bo'lmasa, yangi fayl yaratiladi)
        r = requests.get(url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=15)
        sha = r.json().get("sha") if r.status_code == 200 else None

        payload = {
            "message": message,
            "content": content_b64,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        resp = requests.put(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            log.info("✅ %s GitHub'ga push qilindi → Render auto-deploy boshlanishi mumkin", GITHUB_DATA_PATH)
            return True

        log.error("GitHub push xatosi (%s): %s", resp.status_code, resp.text[:300])
        return False
    except Exception as e:
        log.error("GitHub bilan bog'lanishda xatolik: %s", e)
        return False
