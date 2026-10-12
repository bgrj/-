"""把已解密的微信 4 数据库整理成图里那些消息类型。"""

from __future__ import annotations

import hashlib
import html
import os
import re
import sqlite3
import struct
import subprocess
import urllib.request
from pathlib import Path

import zstandard
from Crypto.Cipher import AES

EXPORTER = Path(os.environ.get("WECHATMSG_EXPORTER", ""))
SELF_WXID = os.environ.get("WECHAT_WXID", "")
ACCOUNT_DIR = Path(os.environ.get("WECHAT_ACCOUNT_DIR", ""))
DB_ROOT = Path(os.environ.get("WECHAT_DB_ROOT", ""))
FFMPEG = Path(os.environ.get("FFMPEG", ""))
if not str(FFMPEG) and EXPORTER:
    FFMPEG = EXPORTER / "exporter" / "resources" / "ffmpeg.exe"
IMAGE_KEY_FILE = Path(os.environ.get("WECHAT_IMAGE_KEY", ""))

LOCAL_KIND = {
    1: "text",
    2: "text",
    3: "image",
    34: "voice",
    42: "contact",
    43: "video",
    47: "emoji",
    48: "location",
    50: "voip",
    64: "voip",
    66: "contact",
    10000: "system",
    25769803825: "file",
    244813135921: "quote",
    81604378673: "merge",
    12884901937: "music",
    8589934592049: "transfer",
    8594229559345: "redenvelope",
    141733920817: "miniapp",
    154618822705: "miniapp",
    219043332145: "channel",
    266287972401: "system",
    4294967345: "link",
    21474836529: "link",
    292057776177: "link",
    17179869233: "link",
    326417514545: "link",
}

APP_KIND = {
    3: "music",
    5: "link",
    6: "file",
    17: "location",
    19: "merge",
    33: "miniapp",
    36: "miniapp",
    57: "quote",
    62: "system",
    2000: "transfer",
    2001: "redenvelope",
}


def load_conversation(wxid: str, media_dir: Path) -> list[dict]:
    media_dir.mkdir(parents=True, exist_ok=True)
    table = "Msg_" + hashlib.md5(wxid.encode()).hexdigest()
    attach = ACCOUNT_DIR / "msg" / "attach" / hashlib.md5(wxid.encode()).hexdigest()
    images = _index_images(attach)
    xor_key = _xor_key(attach)
    voices = _voice_index()
    files = _hardlink_index()
    rows = []
    for db in sorted((DB_ROOT / "message").glob("message_*.db")):
        if any(part in db.name for part in ("fts", "resource", "biz", "media")):
            continue
        con = sqlite3.connect(db)
        names = [item[0] for item in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if table not in names:
            con.close()
            continue
        query = (
            f"SELECT m.server_id, m.create_time, m.local_type, n.user_name, "
            f"m.message_content, m.WCDB_CT_message_content, m.packed_info_data "
            f"FROM [{table}] m LEFT JOIN Name2Id n ON m.real_sender_id=n.rowid"
        )
        for server_id, created, local_type, sender, content, flag, packed in con.execute(query):
            xml = _unz(content, flag)
            rows.append(
                _build(
                    xml,
                    local_type,
                    sender or "",
                    int(created or 0),
                    int(server_id or 0),
                    packed or b"",
                    images,
                    xor_key,
                    voices,
                    files,
                    media_dir,
                )
            )
        con.close()
    rows.sort(key=lambda item: item.get("timestamp") or 0)
    return rows


def _build(xml, local_type, sender, created, server_id, packed, images, xor_key, voices, files, media_dir):
    kind = LOCAL_KIND.get(int(local_type), "card")
    app_type = _first_int(xml, "type")
    if kind in {"quote", "link", "card", "system", "file", "merge", "music", "miniapp", "channel"} and app_type in APP_KIND:
        kind = APP_KIND[app_type]
    if kind == "link" and not _tag(xml, "url"):
        kind = "card"
    message = {
        "kind": kind,
        "is_send": sender == SELF_WXID,
        "timestamp": created,
        "text": "",
        "quote": "",
        "duration": 0,
        "label": "",
    }
    if kind == "text":
        message["text"] = xml
    elif kind == "image":
        path = _decode_image(_md5_from_packed(packed), images, xor_key, media_dir)
        message["image"] = path
    elif kind == "voice":
        length = _attr(xml, "voicemsg", "voicelength")
        message["duration"] = max(1, round(int(length or "0") / 1000)) if length and length.isdigit() else 0
        audio = _decode_voice(server_id, voices, media_dir)
        message["voice_text"] = _voice_text(audio)
    elif kind == "emoji":
        message["image"] = _save_emoji(_attr(xml, "emoji", "cdnurl"), _attr(xml, "emoji", "md5"), media_dir)
        message["text"] = "表情"
    elif kind == "quote":
        message["kind"] = "text"
        message["text"] = _tag(xml, "title")
        message["quote"] = _quote_text(xml)
    elif kind == "file":
        size = _tag(xml, "totallen")
        ext = _tag(xml, "fileext")
        name = _tag(xml, "title") or "文件"
        extra = " · ".join(part for part in (ext.upper(), _human_size(size)) if part)
        message["text"] = name if not extra else f"{name}\n{extra}"
        message["file"] = _lookup_file(files, _tag(xml, "md5"))
    elif kind == "video":
        seconds = _attr(xml, "videomsg", "playlength")
        message["text"] = f"{seconds} 秒" if seconds and seconds.isdigit() else "视频"
        message["image"] = _decode_image(_md5_from_packed(packed), images, xor_key, media_dir)
        message["file"] = _lookup_file(files, _attr(xml, "videomsg", "md5"))
    elif kind == "voip":
        message["text"] = _call_text(xml)
    elif kind == "system":
        message["text"] = _system_text(xml, message["is_send"])
    elif kind == "transfer":
        message["fee"] = _tag(xml, "feedesc") or _tag(xml, "title")
        message["pay_subtype"] = int(_tag(xml, "paysubtype") or 0)
        message["text"] = _tag(xml, "pay_memo")
    elif kind == "redenvelope":
        message["text"] = _tag(xml, "title") or "微信红包"
    elif kind == "location":
        message["text"] = "\n".join(part for part in (_tag(xml, "poiname"), _tag(xml, "label")) if part) or "位置"
    elif kind == "music":
        message["text"] = "\n".join(part for part in (_tag(xml, "title"), _tag(xml, "des")) if part) or "音乐"
        message["url"] = _tag(xml, "url")
    elif kind == "link":
        message["text"] = "\n".join(part for part in (_tag(xml, "title"), _tag(xml, "des")) if part) or "链接"
        message["url"] = _tag(xml, "url")
    elif kind == "contact":
        message["text"] = _tag(xml, "nickname") or _tag(xml, "title") or "名片"
    elif kind == "channel":
        message["text"] = "\n".join(
            part for part in (_tag(xml, "nickname"), _tag(xml, "title"), _tag(xml, "desc")) if part
        ) or "视频号"
    elif kind == "miniapp":
        message["text"] = "\n".join(part for part in (_tag(xml, "title"), _tag(xml, "sourcedisplayname")) if part) or "小程序"
    elif kind == "merge":
        message["text"] = "\n".join(part for part in (_tag(xml, "title"), _tag(xml, "des")) if part) or "聊天记录"
    else:
        message["kind"] = "card"
        message["label"] = "分享卡片"
        message["text"] = _tag(xml, "title") or _tag(xml, "des") or ""
    return message


def _unz(content, flag):
    if not isinstance(content, (bytes, bytearray)):
        return content or ""
    if flag == 4:
        try:
            return zstandard.ZstdDecompressor().decompress(bytes(content)).decode("utf-8", "replace")
        except Exception:
            return ""
    try:
        return bytes(content).decode("utf-8", "replace")
    except Exception:
        return ""


def _tag(xml, name):
    match = re.search(rf"<{name}\b[^>]*><!\[CDATA\[(.*?)\]\]></{name}>", xml or "", re.S)
    if not match:
        match = re.search(rf"<{name}\b[^>]*>(.*?)</{name}>", xml or "", re.S)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def _attr(xml, tag, name):
    match = re.search(rf"<{tag}\b[^>]*\b{name}\s*=\s*\"([^\"]*)\"", xml or "", re.S)
    if not match:
        match = re.search(rf"<{tag}\b[^>]*\b{name}\s*=\s*'([^']*)'", xml or "", re.S)
    return html.unescape(match.group(1)).strip() if match else ""


def _first_int(xml, name):
    text = _tag(xml, name)
    return int(text) if text.isdigit() else 0


def _quote_text(xml):
    match = re.search(r"<refermsg>(.*?)</refermsg>", xml or "", re.S)
    if not match:
        return ""
    inner = html.unescape(match.group(1))
    content = _tag(inner, "content")
    content = html.unescape(content)
    if "<emoji" in content or content.startswith("<msg>"):
        title = _tag(content, "title")
        return title or "[表情]"
    title = _tag(inner, "title") or _tag(content, "title")
    if title:
        return title
    plain = re.sub(r"<[^>]+>", "", content).strip()
    return plain[:120]


def _system_text(xml, is_send):
    text = _tag(xml, "content") or re.sub(r"<[^>]+>", "", xml or "").strip()
    if text == "You recalled a message":
        return "你撤回了一条消息" if is_send else "对方撤回了一条消息"
    return text or _tag(xml, "title")


def _call_text(xml):
    raw = _tag(xml, "msg")
    names = {"Canceled": "已取消", "Rejected": "已拒绝", "NoAnswer": "未接听"}
    label = names.get(raw, raw or "通话")
    seconds = _tag(xml, "duration")
    if seconds.isdigit() and int(seconds) > 0:
        return f"{label} · {int(seconds)} 秒"
    return label


def _human_size(value):
    if not str(value).isdigit():
        return ""
    size = int(value)
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


def _md5_from_packed(packed: bytes) -> str:
    match = re.search(rb"[0-9a-fA-F]{32}", packed or b"")
    return match.group(0).decode().lower() if match else ""


def _index_images(attach: Path) -> dict[str, Path]:
    if not attach.is_dir():
        return {}
    rank = {"": 0, "_h": 1, "_t": 2}
    best = {}
    for path in attach.rglob("*.dat"):
        stem = path.stem
        mark = ""
        digest = stem
        if stem.endswith("_h"):
            mark, digest = "_h", stem[:-2]
        elif stem.endswith("_t"):
            mark, digest = "_t", stem[:-2]
        current = best.get(digest)
        if current is None or rank[mark] < current[0]:
            best[digest] = (rank[mark], path)
    return {digest: item[1] for digest, item in best.items()}


def _xor_key(attach: Path) -> int:
    if not attach.is_dir():
        return 0
    for path in attach.rglob("*_t.dat"):
        data = path.read_bytes()
        if len(data) < 4 or not data.startswith(b"\x07\x08V"):
            continue
        key = data[-2] ^ 0xFF
        if data[-1] ^ key == 0xD9:
            return key
    return 0


def _decode_image(digest, images, xor_key, media_dir: Path) -> str:
    source = images.get(digest or "")
    if source is None or not xor_key:
        return ""
    target = media_dir / "images"
    target.mkdir(parents=True, exist_ok=True)
    key = _image_aes_key()
    if not key:
        return ""
    try:
        return _decrypt_v2(source, target, digest, key, xor_key)
    except Exception:
        return ""


def _image_aes_key() -> bytes:
    if not IMAGE_KEY_FILE.is_file():
        return b""
    text = IMAGE_KEY_FILE.read_text(encoding="utf-8").strip()
    return text.encode("ascii") if len(text) == 16 else b""


def _decrypt_v2(source: Path, folder: Path, name: str, aes_key: bytes, xor_key: int) -> str:
    data = source.read_bytes()
    if data[:6] != b"\x07\x08V2\x08\x07" or len(data) < 31:
        return ""
    aes_size, xor_size = struct.unpack_from("<LL", data, 6)
    aligned = aes_size + 16 if aes_size % 16 == 0 else aes_size + (16 - aes_size % 16)
    offset = 15
    if xor_size > len(data) or offset + aligned > len(data):
        return ""
    decrypted = AES.new(aes_key, AES.MODE_ECB).decrypt(data[offset : offset + aligned])
    pad = decrypted[-1]
    if pad < 1 or pad > 16 or decrypted[-pad:] != bytes([pad]) * pad:
        return ""
    decrypted = decrypted[:-pad]
    offset += aligned
    raw_end = len(data) - xor_size
    raw = data[offset:raw_end] if offset < raw_end else b""
    tail = bytes(byte ^ xor_key for byte in data[raw_end:])
    body = decrypted + raw + tail
    kind = _image_ext(body[:16])
    if kind == "bin":
        return ""
    output = folder / f"{name}.{kind}"
    if not output.exists() or output.stat().st_size < 32:
        output.write_bytes(body)
    return str(output)


def _image_ext(header: bytes) -> str:
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith(b"\x89PNG"):
        return "png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    return "bin"


def _hardlink_index() -> dict[str, Path]:
    db = DB_ROOT / "hardlink" / "hardlink.db"
    if not db.exists():
        return {}
    on_disk = {}
    for folder in ("file", "video"):
        base = ACCOUNT_DIR / "msg" / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                on_disk.setdefault(path.name, path)
    con = sqlite3.connect(db)
    found = {}
    for table in ("file_hardlink_info_v4", "video_hardlink_info_v4"):
        for digest, name in con.execute(f"SELECT md5, file_name FROM {table}"):
            path = on_disk.get(name or "")
            if digest and path:
                found[str(digest).lower()] = path
    con.close()
    return found


def _lookup_file(files: dict[str, Path], digest: str) -> str:
    path = files.get((digest or "").lower())
    return str(path) if path else ""
    found = {}
    db = DB_ROOT / "message" / "media_0.db"
    if not db.exists():
        return found
    con = sqlite3.connect(db)
    for server_id, blob in con.execute("SELECT svr_id, voice_data FROM VoiceInfo"):
        if blob:
            found[int(server_id)] = blob
    con.close()
    return found


def _voice_index() -> dict[int, bytes]:
    found = {}
    db = DB_ROOT / "message" / "media_0.db"
    if not db.exists():
        return found
    con = sqlite3.connect(db)
    for server_id, blob in con.execute("SELECT svr_id, voice_data FROM VoiceInfo"):
        if blob:
            found[int(server_id)] = blob
    con.close()
    return found


_WHISPER = None


def _voice_text(audio: str) -> str:
    if not audio:
        return ""
    source = Path(audio)
    cached = source.with_suffix(".txt")
    if cached.exists() and cached.stat().st_size > 0:
        return cached.read_text(encoding="utf-8").strip()
    global _WHISPER
    if _WHISPER is None:
        import av
        from faster_whisper import WhisperModel

        original = av.open

        def open_audio(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return original(*args, **kwargs)

        av.open = open_audio
        _WHISPER = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _info = _WHISPER.transcribe(
        str(source),
        language="zh",
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    text = "".join(segment.text for segment in segments).strip()
    if text:
        cached.write_text(text, encoding="utf-8")
    return text


def _decode_voice(server_id, voices, media_dir: Path) -> str:
    blob = voices.get(server_id)
    if not blob or not FFMPEG.is_file():
        return ""
    start = blob.find(b"#!SILK")
    if start < 0:
        return ""
    folder = media_dir / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    mp3 = folder / f"{server_id}.mp3"
    if mp3.exists() and mp3.stat().st_size > 100:
        return str(mp3)
    try:
        import pysilk

        pcm = pysilk.decode(blob[start - 1 if start else 0 :], to_wav=False, sample_rate=24000)
        raw = folder / f"{server_id}.pcm"
        raw.write_bytes(pcm)
        subprocess.run(
            [str(FFMPEG), "-loglevel", "quiet", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(raw), str(mp3)],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        return ""
    return str(mp3) if mp3.exists() and mp3.stat().st_size > 100 else ""


def _save_emoji(url, digest, media_dir: Path) -> str:
    if not url.startswith("http"):
        return ""
    folder = media_dir / "emoji"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{digest or 'emoji'}.gif"
    if target.exists() and target.stat().st_size > 50:
        return str(target)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            target.write_bytes(response.read())
    except Exception:
        return ""
    return str(target) if target.exists() and target.stat().st_size > 50 else ""
