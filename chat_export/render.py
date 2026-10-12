"""把聊天记录渲染成微信样式的 HTML，并用本机 Edge 打成 PDF。"""

from __future__ import annotations

import html
import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

TYPE_NAMES = {
    "1": "text",
    "2": "text",
    "3": "image",
    "34": "voice",
    "43": "video",
    "47": "emoji",
    "48": "location",
    "50": "voip",
    "10000": "system",
    "25769803825": "file",
    "8589934592049": "transfer",
    "8594229559345": "redenvelope",
    "244813135921": "quote",
}

TRANSFER_STATUS = {
    1: "发起转账",
    3: "已收款",
    4: "已退还",
    5: "非实时转账收款",
    7: "发起非实时转账",
}


def export_chat(messages, out_dir, title="聊天记录", media_root=None) -> dict:
    """写出 index.html 和 chat.pdf。messages 可以是本工具格式，或 WeChatMsg 的 to_json 列表。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = out_dir / "media"
    media_dir.mkdir(exist_ok=True)
    normalized = normalize_messages(messages)
    _copy_media(normalized, media_dir, Path(media_root) if media_root else None)
    html_path = out_dir / "index.html"
    html_path.write_text(render_html(normalized, title), encoding="utf-8")
    pdf_path = out_dir / "chat.pdf"
    print_pdf(html_path, pdf_path)
    return {"html": html_path, "pdf": pdf_path}


def normalize_messages(messages) -> list:
    if isinstance(messages, dict):
        messages = messages.get("messages", [])
    rows = []
    previous_stamp = None
    for item in messages:
        kind = str(item.get("kind") or item.get("type_name") or "").lower()
        raw_type = str(item.get("type", ""))
        if not kind or kind.isdigit():
            kind = TYPE_NAMES.get(raw_type, kind or "text")
        if kind in {"time", "divider"}:
            rows.append({"kind": "time", "text": item.get("text") or item.get("label") or ""})
            continue
        stamp = _timestamp(item)
        if stamp and previous_stamp and stamp - previous_stamp >= 300 and kind != "system":
            rows.append({"kind": "time", "text": _format_time(stamp)})
        is_send = item.get("is_send", item.get("is_sender", False))
        if isinstance(is_send, str):
            is_send = is_send.lower() in {"1", "true", "yes"}
        rows.append(
            {
                "kind": kind,
                "is_send": bool(is_send),
                "text": item.get("text") or item.get("content") or "",
                "name": item.get("display_name") or item.get("name") or "",
                "avatar": item.get("avatar_src") or item.get("avatar") or "",
                "image": item.get("image") or item.get("path") or item.get("thumb_path") or "",
                "side_image": item.get("side_image") or "",
                "voice_text": item.get("voice_to_text") or item.get("voice_text") or "",
                "duration": _seconds(item.get("duration", 0)),
                "fee": item.get("fee_desc") or item.get("fee") or "",
                "pay_subtype": int(item.get("pay_subtype") or 0),
                "status": item.get("status_text") or item.get("transfer_status") or "",
                "quote": item.get("quote_text") or item.get("quote") or "",
                "label": item.get("label") or "",
                "url": item.get("url") or "",
                "audio": item.get("audio") or "",
                "file": item.get("file") or "",
            }
        )
        if stamp:
            previous_stamp = stamp
    return rows


def render_html(messages, title) -> str:
    body = "\n".join(_render_row(message) for message in messages)
    safe_title = html.escape(title)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
  :root {{
    --bg: #ededed;
    --mine: #95ec69;
    --other: #ffffff;
    --time: #b2b2b2;
    --transfer: #f6c98a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: #111;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 15px;
  }}
  .toolbar {{
    position: sticky;
    top: 0;
    padding: 14px 18px 8px;
    background: linear-gradient(#ededed, rgba(237,237,237,.92));
  }}
  .toolbar input {{
    width: 220px;
    border: none;
    border-radius: 4px;
    padding: 8px 12px;
    font: inherit;
    background: #fff;
    outline: none;
  }}
  .chat {{ padding: 8px 18px 40px; }}
  .time {{
    text-align: center;
    color: var(--time);
    font-size: 12px;
    margin: 18px 0 14px;
  }}
  .system {{
    text-align: center;
    color: #888;
    font-size: 12px;
    margin: 10px 0;
  }}
  .row {{
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin: 14px 0;
  }}
  .row.self {{ flex-direction: row-reverse; }}
  .avatar {{
    width: 40px;
    height: 40px;
    border-radius: 4px;
    object-fit: cover;
    background: #2b2b2b;
    flex: none;
  }}
  .content {{ max-width: min(420px, 72vw); }}
  .bundle {{
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }}
  .bubble {{
    background: var(--other);
    border-radius: 4px;
    padding: 9px 12px;
    line-height: 1.55;
    max-width: 320px;
    word-break: break-word;
    white-space: pre-wrap;
  }}
  .row.self .bubble {{ background: var(--mine); }}
  .side-image, .photo {{
    display: block;
    max-width: 220px;
    max-height: 280px;
    border-radius: 4px;
  }}
  .side-image {{ width: 72px; height: 54px; object-fit: cover; }}
  .voice-line {{
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 72px;
  }}
  .voice-text {{
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid rgba(0, 0, 0, .12);
    color: #111;
    font-size: 15px;
    line-height: 1.5;
  }}
  .transfer {{
    width: 230px;
    background: var(--transfer);
    color: #fff;
    border-radius: 4px;
    padding: 12px 14px 8px;
  }}
  .transfer.pending {{ background: #fa9d3b; }}
  .transfer-main {{ display: flex; gap: 10px; align-items: center; }}
  .transfer-icon {{
    width: 34px;
    height: 34px;
    border-radius: 50%;
    background: rgba(255,255,255,.92);
    color: #e39b3a;
    display: grid;
    place-items: center;
    font-size: 18px;
    flex: none;
  }}
  .fee {{ font-size: 16px; }}
  .status {{ font-size: 12px; opacity: .95; }}
  .transfer-foot {{
    margin-top: 10px;
    padding-top: 6px;
    border-top: 1px solid rgba(255,255,255,.45);
    font-size: 12px;
  }}
  .card {{
    background: #fff;
    border-radius: 4px;
    padding: 10px 12px;
    min-width: 180px;
  }}
  .emoji-img {{
    display: block;
    max-width: 120px;
    max-height: 120px;
  }}
  audio {{ width: 220px; height: 32px; }}
  video {{ max-width: 220px; max-height: 280px; }}
  .card-label {{ color: #888; font-size: 12px; }}
  .card-title {{ margin-top: 4px; word-break: break-word; }}
  .card a {{ color: #576b95; text-decoration: none; word-break: break-all; }}
  .quote {{
    margin-top: 6px;
    padding: 6px 8px;
    background: rgba(0,0,0,.05);
    border-radius: 3px;
    color: #666;
    font-size: 13px;
  }}
  .hidden {{ display: none !important; }}
  @page {{ size: A4; margin: 12mm; }}
  @media print {{
    .toolbar {{ display: none; }}
    .row, .time, .transfer, .photo {{ break-inside: avoid; }}
    body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
  <div class="toolbar"><input id="q" type="search" placeholder="搜索"></div>
  <main class="chat" id="chat">
{body}
  </main>
<script>
  const q = document.getElementById("q");
  q.addEventListener("input", () => {{
    const word = q.value.trim().toLowerCase();
    document.querySelectorAll(".row").forEach((row) => {{
      const text = row.innerText.toLowerCase();
      row.classList.toggle("hidden", word && !text.includes(word));
    }});
  }});
</script>
</body>
</html>
"""


def print_pdf(html_path: Path, pdf_path: Path) -> Path:
    edge = _find_edge()
    if edge is None:
        raise RuntimeError("没有找到 Microsoft Edge，无法把聊天页打印成 PDF")
    pdf_path = Path(pdf_path)
    if pdf_path.exists():
        pdf_path.unlink()
    command = [
        str(edge),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=20000",
        f"--print-to-pdf={pdf_path.resolve()}",
        html_path.resolve().as_uri(),
    ]
    subprocess.run(command, check=False, capture_output=True, timeout=300)
    deadline = time.time() + 20
    while time.time() < deadline and not pdf_path.exists():
        time.sleep(0.4)
    if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
        raise RuntimeError(f"PDF 没有生成：{pdf_path}")
    return pdf_path


def _render_row(message) -> str:
    kind = message["kind"]
    if kind == "time":
        return f'    <div class="time">{html.escape(message["text"])}</div>'
    if kind == "system":
        return f'    <div class="system">{html.escape(message["text"])}</div>'
    side = "self" if message["is_send"] else "other"
    return f'    <div class="row {side}">{_avatar_html(message)}{_body_html(message)}</div>'


def _body_html(message) -> str:
    kind = message["kind"]
    if kind == "emoji" and message["image"]:
        return f'<img class="emoji-img" src="{html.escape(message["image"], quote=True)}" alt="表情">'
    if kind == "image" and message["image"]:
        return f'<img class="photo" src="{html.escape(message["image"], quote=True)}" alt="图片">'
    if kind == "voice":
        seconds = message["duration"] or ""
        label = f'{seconds}"' if seconds != "" else "语音"
        transcript = message["voice_text"] or ""
        extra = f'<div class="voice-text">{html.escape(transcript)}</div>' if transcript else ""
        return (
            '<div class="bubble"><div class="voice-line">'
            '<svg width="20" height="18" viewBox="0 0 24 24" aria-hidden="true">'
            '<path fill="none" stroke="#111" stroke-width="2.2" stroke-linecap="round" d="M7 9.2a4 4 0 0 1 0 5.6"/>'
            '<path fill="none" stroke="#111" stroke-width="2.2" stroke-linecap="round" d="M11 6.2a8 8 0 0 1 0 11.6"/>'
            '<path fill="none" stroke="#111" stroke-width="2.2" stroke-linecap="round" d="M15 3.4a12 12 0 0 1 0 17.2"/>'
            "</svg>"
            f"<span>{html.escape(str(label))}</span></div>{extra}</div>"
        )
    if kind == "transfer":
        status = message["status"] or TRANSFER_STATUS.get(message["pay_subtype"], "转账")
        pending = " pending" if message["pay_subtype"] == 1 else ""
        fee = message["fee"] or message["text"] or ""
        if fee and not str(fee).startswith(("¥", "￥")):
            fee = f"¥ {fee}"
        return (
            f'<div class="transfer{pending}"><div class="transfer-main">'
            '<div class="transfer-icon">✓</div><div>'
            f'<div class="fee">{html.escape(str(fee))}</div>'
            f'<div class="status">{html.escape(status)}</div></div></div>'
            '<div class="transfer-foot">微信转账</div></div>'
        )
    if kind == "redenvelope":
        return (
            '<div class="transfer pending"><div class="transfer-main">'
            '<div class="transfer-icon">¥</div><div>'
            f'<div class="fee">{html.escape(message["text"] or "微信红包")}</div>'
            '<div class="status">微信红包</div></div></div></div>'
        )
    if kind in {"image", "video", "emoji", "file", "location", "voip", "music", "link", "contact", "card", "channel", "miniapp", "merge"}:
        return _card_html(message)
    quote = f'<div class="quote">{html.escape(message["quote"])}</div>' if message["quote"] else ""
    side = ""
    if message["side_image"]:
        side = f'<img class="side-image" src="{html.escape(message["side_image"], quote=True)}" alt="">'
    bubble = f'<div class="bubble">{html.escape(message["text"])}{quote}</div>'
    if side:
        return f'<div class="bundle">{bubble}{side}</div>'
    return bubble


def _card_html(message) -> str:
    kind = message["kind"]
    labels = {
        "image": "图片",
        "video": "视频",
        "emoji": "表情",
        "file": "文件",
        "location": "分享位置",
        "voip": "通话",
        "music": "分享音乐",
        "link": "分享链接",
        "contact": "分享用户",
        "card": "分享卡片",
        "channel": "分享视频号",
        "miniapp": "小程序",
        "merge": "合并转发",
    }
    label = message.get("label") or labels.get(kind, "消息")
    title = html.escape(message.get("text") or "")
    photo = ""
    if message.get("image") and kind == "video":
        photo = f'<img class="photo" src="{html.escape(message["image"], quote=True)}" alt="视频">'
    link = ""
    if message.get("file"):
        safe = html.escape(message["file"], quote=True)
        if message["kind"] == "video":
            link = f'<video controls src="{safe}"></video>'
        else:
            link = f'<div><a href="{safe}">打开文件</a></div>'
    elif message.get("url"):
        safe = html.escape(message["url"], quote=True)
        link = f'<div><a href="{safe}">{html.escape(message["url"])}</a></div>'
    body = f'<div class="card-title">{title}</div>' if title else ""
    return f'{photo}<div class="card"><div class="card-label">{html.escape(label)}</div>{body}{link}</div>'


def _avatar_html(message) -> str:
    if message["avatar"]:
        return f'<img class="avatar" src="{html.escape(message["avatar"], quote=True)}" alt="">'
    return '<div class="avatar"></div>'


def _copy_media(messages, media_dir: Path, media_root: Path | None) -> None:
    cache = {}

    def place(value: str) -> str:
        if not value or value.startswith(("http://", "https://", "data:", "media/")):
            return value
        source = Path(value)
        if not source.is_file() and media_root:
            candidate = media_root / value
            if candidate.is_file():
                source = candidate
        if not source.is_file():
            return value
        key = str(source.resolve())
        if key not in cache:
            target = media_dir / source.name
            if target.exists() and target.resolve() != source.resolve():
                target = media_dir / f"{source.stem}-{len(cache)}{source.suffix}"
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            cache[key] = f"media/{target.name}"
        return cache[key]

    for message in messages:
        if message.get("kind") == "time":
            continue
        for field in ("image", "side_image", "avatar", "audio", "file"):
            if message.get(field):
                message[field] = place(message[field])


def _timestamp(item) -> int | None:
    value = item.get("timestamp")
    if isinstance(value, (int, float)) and value > 10_000:
        return int(value)
    text = item.get("str_time") or item.get("time")
    if not text:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(str(text), pattern).timestamp())
        except ValueError:
            continue
    return None


def _format_time(stamp: int) -> str:
    moment = datetime.fromtimestamp(stamp)
    return f"{moment.year}年{moment.month}月{moment.day}日 {moment.hour:02d}:{moment.minute:02d}"


def _seconds(duration) -> int:
    try:
        value = int(float(duration))
    except (TypeError, ValueError):
        return 0
    if value > 120:
        return max(1, round(value / 1000))
    return value


def _find_edge() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_messages(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
