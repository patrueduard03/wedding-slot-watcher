#!/usr/bin/env python3
"""
backfill.py — one-shot (re-runnable) import of historical checks into Supabase.

Sources:
  1. checks.jsonl        — the local watcher's JSON-lines audit log
  2. GitHub Actions logs — every completed cloud run's `RECORD {...}` line
                           (needs the `gh` CLI, logged in)

Safe to run any number of times: the `checks` table has a unique index on
(source, checked_at) and inserts use ON CONFLICT DO NOTHING semantics
(`Prefer: resolution=ignore-duplicates`), so existing rows are skipped.

Usage:  python3 backfill.py
"""
import json, os, subprocess, sys
import notifier, db_log

HERE = os.path.dirname(os.path.abspath(__file__))
JSONL = os.path.join(HERE, "checks.jsonl")
BATCH = 100


def post_batch(rows, cfg):
    url = str(cfg.get("supabase_url", "")).strip().rstrip("/")
    key = str(cfg.get("supabase_key", "")).strip()
    r = subprocess.run(
        ["curl", "-s", "--max-time", "30",
         "-X", "POST", f"{url}/rest/v1/checks?on_conflict=source,checked_at",
         "-H", f"apikey: {key}",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json",
         "-H", "Prefer: resolution=ignore-duplicates,return=minimal",
         "-d", json.dumps(rows),
         "-o", "/dev/null", "-w", "%{http_code}"],
        capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def local_rows():
    rows = []
    if not os.path.exists(JSONL):
        return rows
    for line in open(JSONL):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("ts"):
            rows.append(db_log.build_row(rec, "local"))
    return rows


def cloud_rows():
    rows = []
    try:
        out = subprocess.run(
            ["gh", "run", "list", "--workflow", "watch.yml", "--limit", "200",
             "--json", "databaseId,status"],
            capture_output=True, text=True, timeout=60).stdout
        runs = [r["databaseId"] for r in json.loads(out) if r["status"] == "completed"]
    except Exception as e:
        print(f"  (skipping cloud logs: gh unavailable — {e})")
        return rows
    for rid in runs:
        try:
            log = subprocess.run(["gh", "run", "view", str(rid), "--log"],
                                 capture_output=True, text=True, timeout=120).stdout
        except Exception:
            continue
        for line in log.splitlines():
            i = line.find("RECORD {")
            if i < 0:
                continue
            try:
                rec = json.loads(line[i + 7:])
            except Exception:
                continue
            if rec.get("ts"):
                rows.append(db_log.build_row(rec, "cloud"))
            break   # one RECORD per run
    return rows


def main():
    cfg = notifier.load_config()
    if not (cfg.get("supabase_url") and cfg.get("supabase_key")):
        sys.exit("Supabase not configured (supabase_url/supabase_key).")

    for name, rows in (("local (checks.jsonl)", local_rows()),
                       ("cloud (Actions logs)", cloud_rows())):
        print(f"{name}: {len(rows)} records")
        for i in range(0, len(rows), BATCH):
            code = post_batch(rows[i:i + BATCH], cfg)
            print(f"  batch {i // BATCH + 1}: HTTP {code}"
                  + ("" if code == "201" else "  <-- unexpected"))
    print("Done. Duplicates were skipped automatically.")


if __name__ == "__main__":
    main()
