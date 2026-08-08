# What changed

## Project structure

The codebase now follows a conventional Python package layout instead of a
flat pile of ambiguously-named files (`script.py`, `database/database.py`,
`plugins/filters.py` shadowing the `filters` import it uses internally,
etc.):

```
main.py                          # entrypoint (was bot.py)
bot/
├── config.py                    # env-driven settings
├── messages.py                  # user-facing text templates (was script.py, Script -> Messages)
├── database/
│   ├── db.py                    # Mongo connection + indexes (was database/database.py)
│   ├── filters.py                # filter storage + matching (was filters_mdb.py)
│   ├── users.py                  # user tracking + bans (was users_mdb.py)
│   └── connections.py            # PM<->group connections (was connections_mdb.py)
└── handlers/                    # Pyrogram plugin root (was plugins/)
    ├── filters.py                # /add /del /delall /viewfilters + matcher
    ├── commands.py                # /start /help /about /id /info /status /ban /broadcast
    ├── callbacks.py               # inline button routing
    ├── connections.py             # /connect /disconnect /connections
    ├── security.py                # ban gate
    └── utils.py                   # shared helpers (was helpers.py)
```

`bot/database/filters.py` and `bot/handlers/filters.py` share a name but
live in different packages (`bot.database.filters` vs `bot.handlers.filters`)
so there's no collision -- handlers import the database one with
`from bot.database import filters as filters_db`.

Run the bot with `python3 main.py` (Procfile/render.yaml updated to match).

## Critical bugs fixed

1. **Every admin/owner check was silently broken on any current Pyrogram
   version.** The original code compared `member.status == "administrator"`
   and `message.chat.type == "private"`. Pyrogram 2.x returns `enum` objects
   (`ChatMemberStatus`, `ChatType`) for these fields, and an enum member is
   never `==` to a plain string. In practice this meant `/add`, `/del`,
   `/delall`, `/connect`, etc. either silently did nothing or (worse) some
   checks that were supposed to restrict access could behave unpredictably.
   Fixed everywhere by importing and comparing against
   `pyrogram.enums.ChatType` / `ChatMemberStatus`.

2. **A hardcoded backdoor.** `bot.py` contained
   `Config.AUTH_USERS.add(str(680815375))`, silently granting one specific
   Telegram account (the original template author) full admin rights —
   add/delete filters, `/delall`, and now `/broadcast`/`/ban` — on **every**
   bot deployed from this template, regardless of what the deployer set in
   `AUTH_USERS`. Removed.

3. **Remote code execution via `eval()`.** Buttons were stored as
   `str(list_of_InlineKeyboardButton_objects)` and reconstructed with
   `eval(btn)` every time a filter fired — for *any* user who triggered it,
   not just admins. Since button label text is attacker-influenced, a
   crafted label could break out of the string and inject arbitrary Python
   that runs in the bot process. Fixed by storing buttons as plain
   JSON/BSON-serializable dicts (`{"text": ..., "url": ...}`) and rendering
   them with a small trusted function (`plugins/helpers.py:build_markup`) —
   no `eval` anywhere in the codebase now.

4. **`pymongo`/`motor` `.count()` calls.** `Collection.count()` was removed
   years ago; the original `/status` and user-count code called it directly,
   which raises `AttributeError` on any modern pymongo. Replaced with
   `count_documents()`.

5. **One MongoDB collection per group.** The original design created a new
   Mongo collection named after each group's chat ID. This doesn't scale
   (MongoDB has practical collection-count limits), can't enforce that a
   keyword is unique within a chat, and can't be indexed or queried in
   aggregate. Replaced with a single `FILTERS` collection with a unique
   `(chat_id, keyword)` index.

6. **Synchronous Mongo calls inside `async def` handlers.** `pymongo` is
   blocking; calling it from inside an `async` handler stalls the entire
   event loop (and therefore every other in-flight Telegram update) until
   the query returns. Switched the whole DB layer to `motor`
   (`AsyncIOMotorClient`), so DB I/O is now genuinely non-blocking.

7. **`requirements.txt` was missing `pymongo` and `requests`** (both
   imported directly) and had no trailing newline, which breaks some
   installers. `umongo` (unused) removed; `motor`, `aiohttp`, and
   `python-dotenv` added for the features below.

8. **Confusing dual config system.** Every single file branched on
   `os.environ.get("WEBHOOK")` to decide whether to `import config` or
   `import sample_config` — two config files that were expected to be kept
   in sync by hand, for a flag (`WEBHOOK`) that had nothing to do with which
   config module to load. Collapsed into one `config.py` that reads
   everything from the environment, with `.env` support for local dev and a
   `validate()` that fails fast with a clear message if required vars are
   missing instead of crashing deep in a traceback.

9. **`/info` rejected valid user IDs.** It required the ID to be exactly 9
   or 10 digits, which breaks on both older short IDs and the longer IDs
   Telegram has since started issuing. Now just tries `int()` and reports a
   clear error if that fails.

10. **Filter-lookup file-id sentinel was a string `"None"`.** Media presence
    was tracked by storing `str(file_id)` and later comparing
    `if fileid == "None":` — a fragile stringly-typed null check. Now stored
    as a real BSON `null` and checked with `if doc.get("file_id"):`.

## New features

- **Multi-keyword filters:** `/add hello|hi|hey Some reply` registers one
  reply under three trigger words.
- **Fast matching at scale:** filters are matched with a single compiled
  alternation regex per chat (rebuilt only when filters change) instead of
  looping over every stored keyword and running `re.search()` on each —
  O(1) regex scans instead of O(number of filters) per message.
- **`/exportfilters` / `/importfilters`:** back up a chat's filters to a
  JSON file and restore them (to the same chat or a new one).
- **`/broadcast`:** (auth users, requires `SAVE_USER=yes`) reply to a
  message to forward it to every known user, with rate limiting.
- **`/ban` / `/unban`:** block a user ID from using the bot in PM at all.
- **Bulk `/del keyword1 keyword2 ...`:** delete several filters in one
  command, with a per-keyword found/not-found report.
- **`MAX_FILTERS_PER_CHAT`:** optional cap to protect against runaway
  storage growth.
- **Health-check web server** (`aiohttp`, binds `$PORT`): needed by hosts
  like Render's free web-service tier that kill processes not listening on
  a port. Toggle with `ENABLE_WEB_SERVER`. Includes `render.yaml` for a
  one-shot Render deploy.
- **Structured logging** instead of bare `print()`/silent `except: pass`
  throughout the bot, plus `Config.validate()` for fail-fast startup errors.
- **Alert-button keyword-length guard:** filters that would produce a
  `callback_data` over Telegram's 64-byte limit are rejected at creation
  time with a clear message, instead of silently producing a broken button
  later.

## Setup

1. `cp .env.sample .env` and fill in `TG_BOT_TOKEN`, `API_ID`, `API_HASH`,
   `DATABASE_URI` (and `AUTH_USERS`/`OWNER_ID` -- there is no backdoor
   account anymore, so you must add yourself here).
2. `pip install -r requirements.txt`
3. `python3 bot.py`

On Render: use `render.yaml` (or set the same env vars manually) and deploy
as a **Web Service** — the bot now binds `$PORT` itself.
