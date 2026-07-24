# Wedding-slot watcher — free, automatic, bulletproof

Watches the Râmnicu Vâlcea civil-marriage page and alerts you (and up to a few
people) by **WhatsApp** the instant a slot at **12:30 or later on 04-09-2026**
turns green. It **only watches and alerts** — you book by hand (step 3 has a
reCAPTCHA and needs both partners' CNP, which is intentionally never automated).

Repo: https://github.com/patrueduard03/wedding-slot-watcher

---

## Why this won't silently fail on you

Five independent safety layers, so there's no realistic way a slot opens and you
aren't told:

| Layer | What it does |
|------|--------------|
| **Cloud watcher** (GitHub Actions) | Checks every ~5 min, always on, no computer needed |
| **Local watcher** (your Mac) | Checks every ~60s — faster, fully redundant, also sends WhatsApp |
| **Heartbeat** | Periodic "✅ still watching" — **email every 15 min to both addresses**, **WhatsApp hourly to you**. If it stops arriving, *that's your warning* the system is down |
| **Failure alert** | If checks start failing (network/site change), it WhatsApps you, and again when it recovers |
| **JSON audit log** | Every check recorded: when + the exact slot grid returned |

> **Honest limit:** no tool can *guarantee* you beat everyone — if someone is
> booking that same minute, they may take it. What this guarantees is that you
> find out as fast as technically possible (≈1 min locally, ≈5 min cloud),
> through multiple channels, and that the system tells you if it ever breaks.

---

## Part A — A free WhatsApp key per recipient (CallMeBot)

> ⚠️ **How CallMeBot works:** a key belongs to **one phone number** and can message
> **only that number**. A key activated for `40712345600` sends only to
> `40712345600`. To message 3 people, **each phone opts in and gets its own key.**
> (This opt-in is the consent/anti-spam rule — a good thing.)

**Each recipient, once, on their own phone:**
1. Save contact **+34 644 51 95 23** (CallMeBot).
2. Send it exactly: `I allow callmebot to send me messages`
3. It replies with **that phone's** API key (a number).

Combine the pairs, comma-separated, no spaces:
```
40712345601:KEY1,40712345602:KEY2,40712345603:KEY3
```

> **Skip the 3 opt-ins:** CallMeBot **WhatsApp Group** mode gives one key that
> messages a whole group — put the people in a group, add CallMeBot, done:
> https://www.callmebot.com/blog/group-message-api/

---

## Part B — The cloud watcher (already deployed)

It's live in the repo and runs every 5 minutes. You only need to give it the key:

### Set the secret
```bash
gh secret set CALLMEBOT_RECIPIENTS --repo patrueduard03/wedding-slot-watcher
```
Paste your `phone:key,phone:key,...` string when prompted. (Telegram optional —
see Part D.) Nothing else to deploy.

### Send yourself a TEST right now
Actions tab → **watch-wedding-slots** → **Run workflow** → tick
**"Send a TEST heartbeat message now"** → Run. You get a WhatsApp within a minute.
(Or: `gh workflow run watch.yml -f force_test=true`.)

### Change what it watches
Edit `.github/workflows/watch.yml` env: `WATCH_DATE`, `WATCH_FROM` ("12:30" means
12:30 or later), `HEARTBEAT_HOURS` (default 1 = hourly "still alive" WhatsApp to
you), `FAIL_THRESHOLD` (default 3).

---

## Part C — The local watcher (faster, run on a Mac that stays on)

Gives ~60-second detection and the same WhatsApp alerts, plus sound + a macOS
popup + it opens the booking page for you.

1. Create your private config (never committed):
   ```bash
   cd ~/Documents/wedding
   cp config.local.example.json config.local.json
   ```
   Edit `config.local.json` and put your `phone:key` pairs in `callmebot_recipients`.
2. Run it (leave the Terminal window open):
   ```bash
   python3 watch_wedding_slots.py
   ```
   Stop with **Ctrl-C**. Live status prints each check; full history is written to
   `checks.jsonl`.

Tune at the top of `watch_wedding_slots.py`: `INTERVAL_SEC` (default 60),
`WATCH_FROM`, `HEARTBEAT_H` (WhatsApp hourly, to you), `EMAIL_HEARTBEAT_MIN`
(email every 15 min, to **all** addresses — keep ≥ 10; Gmail caps ~500/day),
`FAIL_THRESH`.

> Run **both** watchers for maximum safety — cloud covers you when the Mac is off,
> local gives you the fastest possible alert when it's on.

---

## Part D — (Optional) Telegram backup channel

Unlimited, very reliable. Add it alongside WhatsApp (belt-and-suspenders).
1. Telegram → **@BotFather** → `/newbot` → get a **bot token**.
2. Each person opens your bot and taps **Start**.
3. Get each chat id via **@userinfobot**.
4. Cloud: add secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_IDS` (`id1,id2,id3`).
   Local: put the same in `config.local.json`.

Alerts go out on **every** configured channel, so WhatsApp + Telegram = two
independent ways to reach you.

---

## Part E — (Optional) Email to 2+ addresses

Free, unlimited, good extra redundancy. Uses your Gmail via an **App Password**
(not your normal password). The slot alert goes out **high-importance** with a
clear subject; heartbeats/errors go to the first email only.

1. Turn on **2-Step Verification** on your Google account (required for App Passwords).
2. Create the App Password: https://myaccount.google.com/apppasswords → app "Mail"
   → copy the **16-character** password (remove spaces).
3. **Cloud** — add repo secrets (Settings → Secrets and variables → Actions):
   - `SMTP_USER` = your Gmail address
   - `SMTP_PASS` = the 16-char App Password  ← *set this yourself; never paste it in chat*
   - `EMAIL_TO`  = `you@x.com,partner@y.com`  (comma-separated, 2+ is fine)
   - optional: `SMTP_HOST` / `SMTP_PORT` / `SMTP_FROM` (defaults: `smtp.gmail.com` / `587` / your user)
   ```bash
   gh secret set SMTP_USER --repo patrueduard03/wedding-slot-watcher
   gh secret set SMTP_PASS --repo patrueduard03/wedding-slot-watcher
   gh secret set EMAIL_TO  --repo patrueduard03/wedding-slot-watcher
   ```
4. **Local** — put `smtp_user` / `smtp_pass` / `email_to` in `config.local.json`.
5. Test: Run workflow with **force_test** → you get a WhatsApp **and** an email.

> Note: email is **not faster** than WhatsApp — both send within seconds of
> detection. It's for redundancy and reaching a second address. `SMTP_PASS` must
> be the App Password; the code refuses to send if it still looks like a URL.

---

## Part F — Guaranteed 5-min cloud trigger (independent of GitHub's flaky cron)

GitHub's built-in `schedule:` is best-effort and can lag badly. This makes a free
outside service pull the trigger on a reliable clock via the GitHub API. (Verified:
the API endpoint below works — a POST queues a run immediately.)

### Step 1 — Create a GitHub token (you do this; never share it)
1. https://github.com/settings/personal-access-tokens/new (Fine-grained token).
2. **Resource owner:** your account. **Expiration:** e.g. 90 days.
3. **Repository access → Only select repositories →** `wedding-slot-watcher`.
4. **Permissions → Repository permissions → Actions: Read and write** (the only one needed).
5. Generate, copy the token (`github_pat_…`). Treat it like a password.

### Step 2 — (Optional) Test it from your terminal
```bash
curl -sS -X POST \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/patrueduard03/wedding-slot-watcher/actions/workflows/watch.yml/dispatches \
  -d '{"ref":"main"}' -w "HTTP %{http_code}\n"
```
`HTTP 204` = success → a new run appears in the Actions tab.

### Step 3 — Set up the free external cron (cron-job.org)
1. Create a free account at https://cron-job.org and add a cronjob:
   - **URL:** `https://api.github.com/repos/patrueduard03/wedding-slot-watcher/actions/workflows/watch.yml/dispatches`
   - **Schedule:** every 5 minutes
   - **Request method:** `POST`
   - **Headers:**
     - `Authorization: Bearer YOUR_TOKEN_HERE`
     - `Accept: application/vnd.github+json`
     - `Content-Type: application/json`
   - **Body:** `{"ref":"main"}`
2. Save & enable. It now triggers your workflow every 5 min, reliably.

### Security
- The token is **fine-grained, one repo, Actions-only** → minimal damage if leaked.
- Revoke/rotate anytime: https://github.com/settings/tokens
- If GitHub's own cron ever also fires, it's harmless — the `concurrency` group
  serializes runs and `state.json` dedup prevents double alerts.

> Uncomfortable storing a token on cron-job.org? Then skip this and lean on the
> **local watcher** for the fast path (it needs no token and no GitHub scheduler).

---

## Part G — Unified check log in Supabase (already wired)

Every check from **both** watchers is appended to one table (`checks`) in the
`wedding-watcher` Supabase project, so you have a single queryable history:
when each check ran, which source (cloud/local), the exact slot grid returned,
and what was done (none / heartbeat / SLOT_ALERT / error).

- **Security:** the watchers carry the *publishable* key with an **insert-only**
  RLS policy — verified that SELECT/UPDATE/DELETE are refused. Even if the key
  leaked, nobody could read or alter the log with it.
- **Never in the way:** logging is fire-and-forget with a short timeout; if
  Supabase is down or unconfigured, the watcher just prints `db:off`/`db:HTTP…`
  and carries on.
- **Read the log** (Supabase dashboard → SQL editor):
  ```sql
  -- newest check per source: is each watcher alive?
  select * from latest_checks;
  -- anything interesting lately?
  select * from checks where action <> 'none' order by checked_at desc limit 50;
  ```
- Config: `SUPABASE_URL` + `SUPABASE_KEY` (GitHub Secrets, already set) and the
  same fields in `config.local.json` (already added). `sync_secrets.py` syncs them.

---

## How the logic behaves (so nobody gets spammed)

- **Slot alert → everyone.** Sent once when a wanted slot first turns green; not
  repeated while it stays green (unless it closes and reopens).
- **Heartbeat:** email → **both** addresses every 15 min; WhatsApp → **you** hourly.
  Failure/recovery → you only. The 2nd person only ever gets the real "book now"
  alert plus the 15-min email "still alive".
- **Reading the log:** local → `tail -f checks.jsonl`; cloud → each run's log in
  the Actions tab has a `RECORD {...}` line per check (kept ~90 days).

## Good to know
- **Heartbeat:** email every 15 min to **both** addresses + WhatsApp hourly to you,
  each clearly labeled "HEARTBEAT … FUNCTIONEAZA". If they stop arriving, that's
  your signal to check on it. (Keep `EMAIL_HEARTBEAT_MIN` ≥ 10 — Gmail caps ~500
  emails/day, and blowing that cap would block the real alert email too.)
- **Heartbeat clock is cross-checked against the Supabase log:** every heartbeat
  is recorded in the shared `checks` table, and both watchers consult it before
  sending — a local restart or a lost `state.json` can no longer cause duplicate
  heartbeats. If Supabase is unreachable, they fall back to their own clocks
  (heartbeats keep flowing no matter what).
- **60-day rule:** GitHub pauses cron after 60 days of no repo activity. The
  hourly heartbeat commits state, which keeps it alive; you're also well inside
  the window before Sept 4.
- **Want 1-min cloud checks** (instead of 5)? Ask for the Google Apps Script
  version — also free.
