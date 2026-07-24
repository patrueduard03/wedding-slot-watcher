#!/usr/bin/env python3
"""
sync_secrets.py — push your LOCAL config.local.json values up to GitHub Secrets.

Run it whenever you change config.local.json (add email, more recipients, etc.):
    python3 sync_secrets.py

It reads config.local.json (which is gitignored / never committed) and sets the
matching repo secrets via the `gh` CLI. Safe by design:
  * skips empty fields and obvious placeholders
  * refuses to push a password that still looks like the setup URL
Values are set through `gh secret set` on YOUR machine — they are encrypted by
GitHub and never printed here.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CFG  = os.path.join(HERE, "config.local.json")

MAP = {
    "CALLMEBOT_RECIPIENTS": "callmebot_recipients",
    "TELEGRAM_BOT_TOKEN":   "telegram_bot_token",
    "TELEGRAM_CHAT_IDS":    "telegram_chat_ids",
    "SMTP_HOST":            "smtp_host",
    "SMTP_PORT":            "smtp_port",
    "SMTP_USER":            "smtp_user",
    "SMTP_PASS":            "smtp_pass",
    "SMTP_FROM":            "smtp_from",
    "EMAIL_TO":             "email_to",
}


def looks_placeholder(val):
    v = val.lower()
    return (not val) or v.startswith(("your", "http")) or "0000" in val or v in (
        "youraddress@gmail.com", "you@example.com,partner@example.com")


def main():
    if not os.path.exists(CFG):
        sys.exit("config.local.json not found — copy config.local.example.json first.")
    cfg = json.load(open(CFG))

    repo = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner",
                           "-q", ".nameWithOwner"],
                          capture_output=True, text=True).stdout.strip()
    if not repo:
        sys.exit("Could not determine repo. Run `gh auth login` first.")
    print(f"Repo: {repo}")

    set_count = 0
    for secret, key in MAP.items():
        val = str(cfg.get(key, "")).strip()
        if looks_placeholder(val):
            print(f"  skip {secret} (empty/placeholder)")
            continue
        r = subprocess.run(["gh", "secret", "set", secret, "--repo", repo, "--body", val])
        if r.returncode == 0:
            print(f"  ✓ set {secret}")
            set_count += 1
        else:
            print(f"  ✗ FAILED {secret}")
    print(f"Done. {set_count} secret(s) updated.")


if __name__ == "__main__":
    main()
