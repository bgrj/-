# 微信聊天记录一键导出

把聊天记录导出成微信样式的 HTML，并用本机 Microsoft Edge 打成多页 PDF。左右气泡、时间分隔、语音转写都按聊天页的样子排版。

仓库里带了一份示例，可以直接打开：

- [output/demo/index.html](output/demo/index.html)
- [output/demo/chat.pdf](output/demo/chat.pdf)

## 能导出的消息

文本、引用回复、图片、语音、视频、表情、文件、合并转发、系统消息、音乐、链接、名片、位置、分享卡片、视频号、转账、红包、小程序、通话。

语音气泡是波形、时长和转写文字，不放音频播放器。没有转写结果时只显示时长。图片在缺少解密密钥时显示为「图片」卡片。

## 环境

- Python 3.10 及以上
- Microsoft Edge（生成 PDF 时需要）

只跑示例时，不必安装下面这些库。从已解密的微信 4 数据库导出时再装：

```bash
pip install zstandard pycryptodome pysilk faster-whisper
```

语音转写使用 faster-whisper 的 `small` 模型，语言为中文，结果会缓存在音频旁边的 `.txt` 里。仓库自带 `tools/ffmpeg.exe`，也可以用环境变量 `FFMPEG` 换成别的 ffmpeg。

## 生成示例

在仓库根目录执行：

```bash
python -m chat_export --demo
```

默认写到 `output/demo/`，里面有 `index.html`、`chat.pdf` 和 `media/`。

## 从 JSON 导出

消息可以是本工具自己的列表，也可以是带 `messages` 字段的对象。

```bash
python -m chat_export 记录.json -o 输出目录 --title 聊天记录
```

一条消息大致是这样：

```json
{
  "kind": "voice",
  "is_send": false,
  "avatar": "media/avatar.png",
  "duration": 3,
  "voice_text": "好的，谢谢。"
}
```

`kind` 可用 `text`、`image`、`voice`、`video`、`emoji`、`file`、`transfer`、`location`、`link`、`system` 等。图片、头像、文件写相对路径时，会按 JSON 所在目录复制到输出目录的 `media/`。

也可以在代码里调用：

```python
from pathlib import Path
from chat_export.render import export_chat, load_messages

messages = load_messages(Path("记录.json"))
export_chat(messages, Path("输出目录"), title="聊天记录")
```

## 从微信 4 本地库导出

微信 4 的数据库是加密的。先用仓库里的 `wxbak` 在本机解密：它只读取已经登录的微信，不连接微信服务器。需要 Windows、Python 3.9 以上，并用管理员权限运行，微信保持登录。

```bash
pip install -r wxbak/requirements.txt
python wxbak/scripts/wxbak.py selftest
python wxbak/scripts/wxbak.py doctor
python wxbak/scripts/wxbak.py all --who "对方昵称" --self-name 我 --out 导出目录
```

更细的步骤在 [wxbak/README.md](wxbak/README.md)。解密结果里要有 `message/message_*.db`，语音在 `message/media_0.db` 的 `VoiceInfo` 表。把这个目录交给下面的导出程序，生成 HTML 和 PDF。

先设置环境变量，再调用 `load_conversation`：

| 变量 | 作用 |
| --- | --- |
| `WECHAT_WXID` | 自己的 wxid，用来区分左右气泡 |
| `WECHAT_DB_ROOT` | 已解密数据库的根目录 |
| `WECHAT_ACCOUNT_DIR` | 微信账号目录，用来找图片、文件和视频 |
| `WECHAT_IMAGE_KEY` | 图片 AES 密钥文件。没有密钥时图片导出为卡片 |
| `FFMPEG` | ffmpeg 可执行文件。不设置时使用仓库里的 `tools/ffmpeg.exe` |
| `WECHATMSG_EXPORTER` | 可选。仓库里没有 ffmpeg 时，从这里的 `exporter/resources/ffmpeg.exe` 查找 |

```python
import os
from pathlib import Path

os.environ["WECHAT_WXID"] = "自己的wxid"
os.environ["WECHAT_DB_ROOT"] = r"已解密数据库目录"
os.environ["WECHAT_ACCOUNT_DIR"] = r"微信账号目录"
os.environ["FFMPEG"] = r"ffmpeg.exe 的路径"

from chat_export.from_db import load_conversation
from chat_export.render import export_chat

media = Path("媒体缓存")
messages = load_conversation("对方的wxid", media)
export_chat(messages, Path("输出目录"), title="聊天记录", media_root=media)
```

`load_conversation` 的第一个参数是对方的 wxid，不是备注名。

## 目录

```text
chat_export/     把已解密的记录排成 HTML 和 PDF
wxbak/           解密本机微信 4 数据库
tools/ffmpeg.exe 语音转码
output/demo/     示例 HTML 与 PDF
```

## 许可

[MIT](LICENSE)
