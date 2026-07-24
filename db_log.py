#!/usr/bin/env python3
"""
db_log.py — optional unified check-log to Supabase (cloud + local in one table).

Every check record is appended to the `checks` table via PostgREST. The key used
is the *publishable* key with an insert-only RLS policy: it can append rows and
nothing else (reads/updates/deletes are blocked), so it is safe to keep in
config.local.json / GitHub Secrets.

Hard rule: logging must NEVER break or delay the watcher. Short timeout, all
errors swallowed (returned as a string for the console, nothing raised).

Config (via notifier.load_config()): supabase_url + supabase_key
(env SUPABASE_URL / SUPABASE_KEY win over config.local.json).
If unconfigured, log_check() is a silent no-op.
"""
import json, subprocess


def build_row(record, source):
    """Map a watcher record dict to a `checks` table row."""
    return {
        "checked_at": record.get("ts"),
        "source": source,
        "watch_date": record.get("date", ""),
        "watch_from": record.get("watch_from"),
        "action": record.get("action", "none"),
        "grid": record.get("grid"),
        "available": record.get("available"),
        "matches": record.get("matches"),
        "heartbeat": bool(record.get("heartbeat") or record.get("heartbeat_msg")
                          or record.get("heartbeat_email")),
        "error": record.get("error"),
        "consecutive_fails": record.get("consecutive_fails"),
        "notify": record.get("notify"),
    }


def log_check(record, source, cfg):
    """Append one check record. Returns a short status string (never raises)."""
    url = str(cfg.get("supabase_url", "")).strip().rstrip("/")
    key = str(cfg.get("supabase_key", "")).strip()
    if not url or not key:
        return "db:off"

    row = build_row(record, source)
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "8",
             "-X", "POST", f"{url}/rest/v1/checks",
             "-H", f"apikey: {key}",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-H", "Prefer: return=minimal",
             "-d", json.dumps(row),
             "-o", "/dev/null", "-w", "%{http_code}"],
            capture_output=True, text=True, timeout=12)
        code = r.stdout.strip()
        return "db:OK" if code == "201" else f"db:HTTP{code or '?'}"
    except Exception as e:
        return f"db:err({str(e)[:40]})"


def last_seen(source, cfg):
    """Newest checked_at (ISO string) logged by `source`, or None.

    Uses the watchers' key, which may read ONLY (source, checked_at) via a
    column-level grant — no other data is accessible. Never raises.
    """
    url = str(cfg.get("supabase_url", "")).strip().rstrip("/")
    key = str(cfg.get("supabase_key", "")).strip()
    if not url or not key:
        return None
    try:
        r = subprocess.run(
            ["curl", "-s", "--max-time", "8",
             f"{url}/rest/v1/checks?select=checked_at&source=eq.{source}"
             f"&order=checked_at.desc&limit=1",
             "-H", f"apikey: {key}",
             "-H", f"Authorization: Bearer {key}"],
            capture_output=True, text=True, timeout=12)
        rows = json.loads(r.stdout)
        return rows[0]["checked_at"] if rows else None
    except Exception:
        return None
