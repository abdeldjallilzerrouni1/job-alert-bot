import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup


@dataclass
class JobHit:
    source: str
    title: str
    link: str
    snippet: str


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "seen_jobs.db"

DUCKDUCKGO_HTML = "https://duckduckgo.com/html/"

SOURCES = {
    "LinkedIn": "site:linkedin.com/jobs",
    "HelloWork": "site:hellowork.com",
    "Indeed": "site:indeed.com",
    "WelcomeToTheJungle": "site:welcometothejungle.com",
    "LaBonneAlternance": "site:labonnealternance.apprentissage.beta.gouv.fr OR site:labonnealternance",
}

DEFAULT_TITLE_KEYWORDS = ["alternance", "alternant", "apprenti"]
DEFAULT_DESC_KEYWORDS = ["solidworks", "catia", "creo", "topsolid", "solidedge"]


def env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_jobs (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.commit()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    t = normalize(text)
    return any(k in t for k in keywords)


def build_query(site_expr: str, title_keywords: list[str], desc_keywords: list[str], region: str) -> str:
    title_clause = " OR ".join([f'"{k}"' for k in title_keywords])
    desc_clause = " OR ".join([f'"{k}"' for k in desc_keywords])
    pieces = [site_expr, f"({title_clause})", f"({desc_clause})", '"offre"']
    if region:
        pieces.append(f'"{region}"')
    return " ".join(pieces)


def duckduckgo_search(query: str, timeout_s: int, max_results: int) -> list[JobHit]:
    params = {"q": query, "kl": "fr-fr"}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(DUCKDUCKGO_HTML, params=params, headers=headers, timeout=timeout_s)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[JobHit] = []
    for card in soup.select(".result"):
        link_tag = card.select_one(".result__a")
        if not link_tag:
            continue
        link = (link_tag.get("href") or "").strip()
        title = link_tag.get_text(" ", strip=True)
        snippet_tag = card.select_one(".result__snippet")
        snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
        if not link or not title:
            continue
        items.append(JobHit(source="", title=title, link=link, snippet=snippet))
        if len(items) >= max_results:
            break
    return items


def make_id(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8", errors="ignore")).hexdigest()


def already_seen(job_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT 1 FROM seen_jobs WHERE id = ? LIMIT 1", (job_id,))
        return cur.fetchone() is not None


def save_seen(job: JobHit) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_jobs (id, source, title, link, seen_at) VALUES (?, ?, ?, ?, ?)",
            (
                make_id(job.link),
                job.source,
                job.title[:500],
                job.link[:1000],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def telegram_send(bot_token: str, chat_id: str, message: str, timeout_s: int) -> None:
    url = f"https://api.telegram.org/bot{quote_plus(bot_token)}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message[:4000],
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=timeout_s)
    r.raise_for_status()


def get_meta(key: str) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT value FROM bot_meta WHERE key = ? LIMIT 1", (key,))
        row = cur.fetchone()
        return row[0] if row else None


def set_meta(key: str, value: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO bot_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def get_daily_counts_utc() -> tuple[int, dict[str, int]]:
    now_utc = datetime.now(timezone.utc)
    day_start = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc).isoformat()
    day_end = datetime(now_utc.year, now_utc.month, now_utc.day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cur_total = conn.execute(
            "SELECT COUNT(*) FROM seen_jobs WHERE seen_at >= ? AND seen_at <= ?",
            (day_start, day_end),
        )
        total = int(cur_total.fetchone()[0])
        cur_sources = conn.execute(
            "SELECT source, COUNT(*) FROM seen_jobs WHERE seen_at >= ? AND seen_at <= ? GROUP BY source",
            (day_start, day_end),
        )
        per_source = {str(src): int(cnt) for src, cnt in cur_sources.fetchall()}
    return total, per_source


def format_job(job: JobHit) -> str:
    snippet = (job.snippet or "").strip()
    if len(snippet) > 300:
        snippet = snippet[:297] + "..."
    return (
        f"NOUVELLE OFFRE ({job.source})\n"
        f"Titre: {job.title}\n"
        f"Lien: {job.link}\n"
        f"Extrait: {snippet}"
    )


def run_once() -> dict:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token or not chat_id:
        print("Variables manquantes: TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID")
        return {"code": 2, "new_hits": 0, "bot_token": "", "chat_id": "", "timeout_s": 25}

    timeout_s = int(os.getenv("HTTP_TIMEOUT_SECONDS", "25"))
    max_results = int(os.getenv("MAX_RESULTS_PER_SOURCE", "25"))
    region = os.getenv("REGION_FILTER", "").strip()
    title_keywords = env_list("TITLE_KEYWORDS", DEFAULT_TITLE_KEYWORDS)
    desc_keywords = env_list("DESC_KEYWORDS", DEFAULT_DESC_KEYWORDS)

    new_hits: list[JobHit] = []

    for source_name, site_expr in SOURCES.items():
        query = build_query(site_expr, title_keywords, desc_keywords, region)
        try:
            raw_hits = duckduckgo_search(query=query, timeout_s=timeout_s, max_results=max_results)
        except Exception as e:
            print(f"[WARN] Source {source_name} indisponible: {e}")
            continue

        for hit in raw_hits:
            hit.source = source_name
            combined = f"{hit.title} {hit.snippet}"
            if not contains_any(hit.title, title_keywords):
                continue
            if not contains_any(combined, desc_keywords):
                continue
            job_id = make_id(hit.link)
            if already_seen(job_id):
                continue
            save_seen(hit)
            new_hits.append(hit)

    if not new_hits:
        print(f"{datetime.now().isoformat()} - Aucune nouvelle offre.")
        return {
            "code": 0,
            "new_hits": 0,
            "bot_token": bot_token,
            "chat_id": chat_id,
            "timeout_s": timeout_s,
        }

    print(f"{datetime.now().isoformat()} - {len(new_hits)} nouvelles offres.")
    for job in new_hits:
        try:
            telegram_send(bot_token, chat_id, format_job(job), timeout_s=timeout_s)
        except Exception as e:
            print(f"[WARN] Notification Telegram échouée: {e} | {job.link}")
    return {
        "code": 0,
        "new_hits": len(new_hits),
        "bot_token": bot_token,
        "chat_id": chat_id,
        "timeout_s": timeout_s,
    }


def main() -> int:
    init_db()
    mode = os.getenv("RUN_MODE", "daemon").strip().lower()
    interval_min = int(os.getenv("POLL_MINUTES", "15"))
    smart_mode = os.getenv("SMART_SCHEDULE", "1").strip().lower() in {"1", "true", "yes", "y"}
    day_interval_min = int(os.getenv("DAY_POLL_MINUTES", "5"))
    night_interval_min = int(os.getenv("NIGHT_POLL_MINUTES", "15"))
    day_start_hour = int(os.getenv("DAY_START_HOUR", "8"))
    day_end_hour = int(os.getenv("DAY_END_HOUR", "22"))
    notify_empty_scan = os.getenv("NOTIFY_EMPTY_SCAN", "1").strip().lower() in {"1", "true", "yes", "y"}
    empty_notify_every = int(os.getenv("EMPTY_SCAN_NOTIFY_EVERY", "3"))
    recap_hour = int(os.getenv("DAILY_RECAP_HOUR", "22"))
    recap_enabled = os.getenv("DAILY_RECAP_ENABLED", "1").strip().lower() in {"1", "true", "yes", "y"}
    empty_scan_streak = 0

    if mode == "once":
        return int(run_once()["code"])

    if smart_mode:
        print(
            "Démarrage bot 24/7 (mode intelligent): "
            f"{day_interval_min} min entre {day_start_hour}h-{day_end_hour}h, "
            f"{night_interval_min} min la nuit."
        )
    else:
        print(f"Démarrage bot 24/7. Intervalle fixe: {interval_min} minute(s).")
    while True:
        result = run_once()
        if result["new_hits"] > 0:
            empty_scan_streak = 0
        else:
            empty_scan_streak += 1
            if (
                notify_empty_scan
                and result["bot_token"]
                and result["chat_id"]
                and empty_scan_streak % max(empty_notify_every, 1) == 0
            ):
                try:
                    telegram_send(
                        result["bot_token"],
                        result["chat_id"],
                        f"Scan effectué ({datetime.now().strftime('%Y-%m-%d %H:%M')}) : aucune nouvelle offre.",
                        timeout_s=int(result["timeout_s"]),
                    )
                except Exception as e:
                    print(f"[WARN] Message scan vide non envoyé: {e}")

        if recap_enabled and result["bot_token"] and result["chat_id"] and datetime.now().hour == recap_hour:
            recap_key = "last_daily_recap_date_utc"
            today_utc = datetime.now(timezone.utc).date().isoformat()
            if get_meta(recap_key) != today_utc:
                total, per_source = get_daily_counts_utc()
                ordered_sources = list(SOURCES.keys())
                lines = [f"- {src}: {per_source.get(src, 0)}" for src in ordered_sources]
                recap_msg = (
                    f"Récap du jour ({today_utc})\n"
                    f"Total nouvelles offres: {total}\n"
                    + "\n".join(lines)
                )
                try:
                    telegram_send(
                        result["bot_token"],
                        result["chat_id"],
                        recap_msg,
                        timeout_s=int(result["timeout_s"]),
                    )
                    set_meta(recap_key, today_utc)
                except Exception as e:
                    print(f"[WARN] Récap quotidien non envoyé: {e}")

        if smart_mode:
            hour = datetime.now().hour
            is_day = day_start_hour <= hour < day_end_hour
            next_interval_min = day_interval_min if is_day else night_interval_min
        else:
            next_interval_min = interval_min
        time.sleep(max(next_interval_min, 1) * 60)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Arrêt manuel.")
        sys.exit(130)
