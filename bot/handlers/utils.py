import hashlib
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
CALLBACK_DATA_MAX_BYTES = 64
ALERT_TOKEN_LENGTH = 16


def alert_token(keyword: str) -> str:
    """Return a stable compact token for a keyword used in alert callbacks."""
    return hashlib.sha256(keyword.encode("utf-8")).hexdigest()[:ALERT_TOKEN_LENGTH]


def is_auth(user_id) -> bool:
    """True if the given user id is an authorized bot operator."""
    uid = str(user_id)
    return uid in Config.AUTH_USERS or (Config.OWNER_ID and int(user_id) == Config.OWNER_ID)


async def is_chat_admin(client, chat_id, user_id) -> bool:
    """True if the user is an admin/creator of chat_id, or a global auth user."""
    if is_auth(user_id):
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
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
    """Parse button markup into JSON/BSON-serializable structures."""
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
            same_row = bool(match.group(5)) and bool(buttons)
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
    """Reconstruct an InlineKeyboardMarkup from stored button data."""
    if not buttons:
        return None

    rows = []
    token = alert_token(keyword)
    for row in buttons:
        btn_row = []
        for btn in row:
            if "url" in btn:
                btn_row.append(InlineKeyboardButton(text=btn["text"], url=btn["url"]))
            elif "alert" in btn:
                data = f"alrt:{btn['alert']}:{token}"
                if len(data.encode("utf-8")) <= CALLBACK_DATA_MAX_BYTES:
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
