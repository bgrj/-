"""命令行：python -m chat_export --demo 或 python -m chat_export 记录.json -o 输出目录"""

import argparse
from pathlib import Path

from chat_export.assets import ensure_demo_assets
from chat_export.render import export_chat, load_messages


def demo_messages(assets: dict) -> list:
    landscape = str(assets["landscape"])
    other = str(assets["other"])
    mine = str(assets["self"])
    return [
        {
            "kind": "text",
            "is_send": False,
            "avatar": other,
            "text": "对了，有个急事想麻烦你……能借我点钱吗？月底交房租差点\n预算",
        },
        {
            "kind": "text",
            "is_send": True,
            "avatar": mine,
            "text": "可以，具体什么时候还？",
            "side_image": landscape,
        },
        {
            "kind": "text",
            "is_send": False,
            "avatar": other,
            "text": "下个月15号发工资立刻还你，谢谢！",
        },
        {"kind": "time", "text": "2025年4月3日 12:39"},
        {
            "kind": "transfer",
            "is_send": False,
            "avatar": other,
            "fee": "0.01",
            "pay_subtype": 3,
        },
        {
            "kind": "voice",
            "is_send": False,
            "avatar": other,
            "duration": 3,
            "voice_text": "好的兄弟，谢谢谢谢\n谢谢兄弟。",
        },
        {"kind": "time", "text": "2025年4月3日 14:25"},
        {
            "kind": "image",
            "is_send": False,
            "avatar": other,
            "image": landscape,
        },
        {
            "kind": "text",
            "is_send": False,
            "avatar": other,
            "text": "天气不错，有空出来一起露营🌲",
        },
        {"kind": "time", "text": "2025年12月3日 10:45"},
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="把聊天记录导出成微信样式的 HTML 和 PDF")
    parser.add_argument("json_file", nargs="?", help="聊天 JSON。可使用 WeChatMsg 导出的消息列表")
    parser.add_argument("-o", "--output", default="output/chat", help="输出目录")
    parser.add_argument("--demo", action="store_true", help="用示意图里的示例聊天生成 HTML 和 PDF")
    parser.add_argument("--title", default="聊天记录")
    args = parser.parse_args()
    output = Path(args.output)
    if args.demo or not args.json_file:
        assets = ensure_demo_assets(Path(__file__).resolve().parent / "assets")
        messages = demo_messages(assets)
        title = "示例聊天"
        output = Path("output/demo") if args.output == "output/chat" else output
    else:
        messages = load_messages(Path(args.json_file))
        title = args.title
    result = export_chat(messages, output, title=title, media_root=Path(args.json_file).parent if args.json_file else None)
    print(result["html"])
    print(result["pdf"])


if __name__ == "__main__":
    main()
