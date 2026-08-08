import re
from typing import List, Optional, Tuple

from pyrogram.enums import ChatMemberStatus
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import Config

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)

SMART_OPEN = "\u201c"
SMART_CLOSE = "\u201d"
START_CHAR = ("'", '"', SMART_OPEN)

# Telegram hard-caps callback_data at 64 bytes.
CALLBACK_DATA_MAX_BYTES = 64


def is_auth(user_id) -> bool:
    """True if the given user id is an authorized bot operator (owner or AUTH_USERS)."""
    uid = str(user_id)
    return uid in Config.AUTH_USERS or (Config.OWNER_ID and int(user_id) == Config.OWNER_ID)


async def is_chat_admin(client, chat_id, user_id) -> bool:
    """True if the user is an admin/creator of chat_id, or a global auth user.

    Never raises: on any API error (bot not in chat, user not a member, etc.)
    this fails closed (returns False) instead of letting an exception escape
    into the handler and silently do nothing (the original code let
    get_chat_member() exceptions propagate, which meant a single bad lookup
    could crash the message handler and drop the update).
    """
    if is_auth(user_id):
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        # Pyrogram 2.x returns a ChatMemberStatus enum, not a plain string --
        # comparing it with `member.status == "administrator"` (as the
        # original code did) is always False on any current Pyrogram
        # version, which silently broke every admin check in the bot.
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


def split_quotes(text: str) -> List[str]:
    if any(text.startswith(char) for char in START_CHAR):
        counter = 1
        while counter < len(text):
            if text[counter] == "\\":
                counter += 1
            elif text[counter] == text[0] or (text[0] == SMART_OPEN and text[counter] == SMART_CLOSE):
                break
            counter += 1
        else:
            return text.split(None, 1)

        key = remove_escapes(text[1:counter].strip())
        rest = text[counter + 1:].strip()
        if not key:
            key = text[0] + text[0]
        return list(filter(None, [key, rest]))
    else:
        return text.split(None, 1)


def remove_escapes(text: str) -> str:
    counter = 0
    res = ""
    is_escaped = False
    while counter < len(text):
        if is_escaped:
            res += text[counter]
            is_escaped = False
        elif text[counter] == "\\":
            is_escaped = True
        else:
            res += text[counter]
        counter += 1
    return res


def parse_buttons(text: str) -> Tuple[str, List[List[dict]], List[str]]:
    """Parse `[label](buttonurl:...)` / `[label](buttonalert:...)` markup.

    Returns (clean_text, buttons, alerts) where `buttons` is a plain
    JSON/BSON-serializable structure: a list of rows, each row a list of
    dicts like {"text": "...", "url": "..."} or {"text": "...", "alert": 0}.

    This intentionally avoids ever producing a Python-source string that
    later gets eval()'d -- see bot/handlers/filters.py for why that mattered.
    """
    if "buttonalert" in text:
        text = text.replace("\n", "\\n").replace("\t", "\\t")

    buttons: List[List[dict]] = []
    alerts: List[str] = []
    note_data = ""
    prev = 0
    alert_index = 0

    for match in BTN_URL_REGEX.finditer(text):
        n_escapes = 0
        to_check = match.start(1) - 1
        while to_check > 0 and text[to_check] == "\\":
            n_escapes += 1
            to_check -= 1

        if n_escapes % 2 == 0:
            note_data += text[prev:match.start(1)]
            prev = match.end(1)
            label = match.group(2)
            same_row = bool(match.group(5)) and buttons

            if match.group(3) == "buttonalert":
                btn = {"text": label, "alert": alert_index}
                alerts.append(match.group(4))
                alert_index += 1
            else:
                btn = {"text": label, "url": match.group(4).replace(" ", "")}

            if same_row:
                buttons[-1].append(btn)
            else:
                buttons.append([btn])
        else:
            note_data += text[prev:to_check]
            prev = match.start(1) - 1
    else:
        note_data += text[prev:]

    return note_data, buttons, alerts


def build_markup(buttons: List[List[dict]], chat_id, keyword: str) -> Optional[InlineKeyboardMarkup]:
    """Reconstruct an InlineKeyboardMarkup from stored button data.

    Alert-button callback_data is `alrt:{index}:{keyword}`. Telegram caps
    callback_data at 64 bytes, so long keywords are hashed instead of used
    verbatim -- see filters.py's validation at filter-creation time, which
    rejects alert buttons on keywords that can't fit.
    """
    if not buttons:
        return None

    rows = []
    for row in buttons:
        btn_row = []
        for btn in row:
            if "url" in btn:
                btn_row.append(InlineKeyboardButton(text=btn["text"], url=btn["url"]))
            elif "alert" in btn:
                data = f"alrt:{btn['alert']}:{keyword}"
                if len(data.encode()) > CALLBACK_DATA_MAX_BYTES:
                    data = f"alrt:{btn['alert']}:{keyword[:20]}"
                btn_row.append(InlineKeyboardButton(text=btn["text"], callback_data=data))
        if btn_row:
            rows.append(btn_row)

    return InlineKeyboardMarkup(rows) if rows else None


def humanbytes(size) -> str:
    if not size:
        return "0 B"
    power = 2 ** 10
    n = 0
    labels = {0: "", 1: "Ki", 2: "Mi", 3: "Gi", 4: "Ti"}
    size = float(size)
    while size > power and n < 4:
        size /= power
        n += 1
    return f"{round(size, 2)} {labels[n]}B"


def hhmmss(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}h {m:02d}m {s:02d}s"
