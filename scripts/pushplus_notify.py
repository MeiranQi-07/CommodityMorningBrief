#!/usr/bin/env python3
"""
pushplus_notify.py — 通过 PushPlus / 邮件推送 CommodityMorningBrief

依赖: curl (系统自带, 无需 pip install)
配置: 使用环境变量或 .env 文件

用法:
    python3 scripts/pushplus_notify.py [--to token] [--date 20260603]
    python3 scripts/pushplus_notify.py --email --date 20260603
"""

import argparse
import html
import json
import os
import re
import smtplib
import subprocess
import urllib.request
from datetime import datetime
from email.message import EmailMessage

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "scripts" else SCRIPT_DIR
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def load_dotenv():
    """读取简单 .env，不覆盖系统环境变量。"""
    env = {}
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return env

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("\"'")
    return env


DOTENV = load_dotenv()


def get_config(name, default=""):
    return os.environ.get(name) or DOTENV.get(name, default)


def str_to_bool(value, default=False):
    if value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def get_token():
    """获取 PushPlus token: 环境变量 > .env > 用户输入"""
    return get_config("PUSHPLUS_TOKEN")


def send_push(title, content, template="markdown", channel="wechat"):
    """通过 PushPlus 发送微信推送"""
    token = get_token()
    if not token:
        print("❌ 未配置 PUSHPLUS_TOKEN")
        print("   请设置环境变量或添加到 .env: PUSHPLUS_TOKEN=your_token")
        print("   注册: https://www.pushplus.plus")
        return False

    payload = json.dumps({
        "token": token,
        "title": title,
        "content": content,
        "template": template,
        "channel": channel,
    }, ensure_ascii=False)

    cmd = [
        "curl", "-s", "-X", "POST",
        "https://www.pushplus.plus/send",
        "-H", "Content-Type: application/json",
        "-d", payload,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        resp = json.loads(result.stdout)
        if resp.get("code") == 200:
            print(f"✅ PushPlus 推送成功: {title}")
            return True
        else:
            print(f"❌ PushPlus 推送失败: {resp}")
            return False
    except Exception as e:
        print(f"❌ PushPlus 异常: {e}")
        return False


def build_report_content(date):
    """从生成的 Markdown 报告中提取内容格式化为推送文本"""
    report_path = os.path.join(OUTPUT_DIR, f"morning_brief_{date}.md")
    if not os.path.exists(report_path):
        # 用当前日期回退
        today = datetime.now().strftime("%Y%m%d")
        report_path = os.path.join(OUTPUT_DIR, f"morning_brief_{today}.md")

    if not os.path.exists(report_path):
        return f"报告文件未找到 (morning_brief_{date}.md), 请先生成报告。"

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    return content


def split_markdown_table(lines, start_index):
    table_lines = []
    index = start_index
    while index < len(lines) and "|" in lines[index]:
        table_lines.append(lines[index])
        index += 1
    return table_lines, index


def is_table_separator(line):
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.match(r"^:?-{3,}:?$", cell or "") for cell in cells)


def render_inline(text):
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def render_markdown_table(table_lines):
    rows = []
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)

    if len(rows) >= 2 and is_table_separator(table_lines[1]):
        headers = rows[0]
        body_rows = rows[2:]
    else:
        headers = []
        body_rows = rows

    html_rows = []
    if headers:
        header_cells = "".join(f"<th>{render_inline(cell)}</th>" for cell in headers)
        html_rows.append(f"<thead><tr>{header_cells}</tr></thead>")

    body_html = []
    for row in body_rows:
        body_html.append("<tr>" + "".join(f"<td>{render_inline(cell)}</td>" for cell in row) + "</tr>")
    if body_html:
        html_rows.append("<tbody>" + "".join(body_html) + "</tbody>")

    return '<table role="presentation">' + "".join(html_rows) + "</table>"


def markdown_to_html(markdown_text, title):
    lines = markdown_text.splitlines()
    body = []
    in_list = False
    index = 0

    def close_list():
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()

        if not stripped:
            close_list()
            index += 1
            continue

        if "|" in stripped and index + 1 < len(lines) and is_table_separator(lines[index + 1]):
            close_list()
            table_lines, index = split_markdown_table(lines, index)
            body.append(render_markdown_table(table_lines))
            continue

        if stripped.startswith("#"):
            close_list()
            level = min(len(stripped) - len(stripped.lstrip("#")), 3)
            text = stripped[level:].strip()
            body.append(f"<h{level}>{render_inline(text)}</h{level}>")
            index += 1
            continue

        if stripped.startswith(("- ", "* ")):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{render_inline(stripped[2:].strip())}</li>")
            index += 1
            continue

        if re.match(r"^\d+\.\s+", stripped):
            close_list()
            text = re.sub(r"^\d+\.\s+", "", stripped)
            body.append(f"<p>{render_inline(text)}</p>")
            index += 1
            continue

        if re.match(r"^-{3,}$", stripped):
            close_list()
            body.append("<hr>")
            index += 1
            continue

        close_list()
        body.append(f"<p>{render_inline(stripped)}</p>")
        index += 1

    close_list()
    body_html = "\n".join(body)
    safe_title = html.escape(title)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background: #f4f6f8;
      color: #1f2933;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, "Microsoft YaHei", sans-serif;
      line-height: 1.65;
    }}
    .wrap {{
      max-width: 760px;
      margin: 0 auto;
      padding: 24px 14px;
    }}
    .panel {{
      background: #ffffff;
      border: 1px solid #e3e8ef;
      border-radius: 8px;
      overflow: hidden;
    }}
    .header {{
      padding: 22px 26px;
      background: #102a43;
      color: #ffffff;
    }}
    .header h1 {{
      margin: 0;
      font-size: 22px;
      line-height: 1.35;
      letter-spacing: 0;
    }}
    .meta {{
      margin-top: 8px;
      color: #bcccdc;
      font-size: 13px;
    }}
    .content {{
      padding: 24px 26px 30px;
    }}
    h1, h2, h3 {{
      margin: 22px 0 10px;
      color: #102a43;
      letter-spacing: 0;
    }}
    h1 {{ font-size: 22px; }}
    h2 {{ font-size: 18px; border-bottom: 1px solid #e6edf5; padding-bottom: 7px; }}
    h3 {{ font-size: 16px; }}
    p {{
      margin: 10px 0;
      font-size: 14px;
    }}
    ul {{
      margin: 8px 0 14px;
      padding-left: 22px;
    }}
    li {{
      margin: 6px 0;
      font-size: 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
      font-size: 13px;
    }}
    th {{
      background: #edf2f7;
      color: #102a43;
      font-weight: 700;
    }}
    th, td {{
      border: 1px solid #d9e2ec;
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    tr:nth-child(even) td {{
      background: #f8fafc;
    }}
    hr {{
      border: 0;
      border-top: 1px solid #e6edf5;
      margin: 20px 0;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <div class="header">
        <h1>{safe_title}</h1>
        <div class="meta">CommodityMorningBrief · {generated_at}</div>
      </div>
      <div class="content">
        {body_html}
      </div>
    </div>
  </div>
</body>
</html>"""


def format_for_feishu(content, title):
    """将 Markdown 内容转为飞书友好的格式（无表格，用文本排版）"""
    lines = content.split("\n")
    feishu_lines = []

    # 板块标题 → emoji 映射
    SECTION_EMOJI = {
        "一、隔夜行情速览": "📊",
        "二、新闻概览": "📰",
        "三、重点新闻摘要": "🔥",
        "四、黄金影响分析": "🥇",
        "五、白银影响分析": "🪙",
        "六、原油与大宗商品影响分析": "🛢️",
        "今日关注因素": "🎯",
        "回测验证": "📈",
        "模型自我复盘": "🤖",
        "风险提示": "⚠️",
        "系统说明": "ℹ️",
        "整体准确率": "📊",
        "各资产回测明细": "🔍",
    }

    # 提取关键板块
    current_section = ""
    for line in lines:
        stripped = line.strip()

        # 跳过纯分隔线
        if stripped.startswith("|---"):
            continue

        # 识别板块标题，替换为 emoji
        if stripped.startswith("## "):
            raw_section = stripped.replace("## ", "").strip()
            current_section = raw_section
            # 匹配对应的 emoji
            emoji = ""
            for key, e in SECTION_EMOJI.items():
                if key in raw_section or raw_section in key:
                    emoji = e
                    break
            if emoji:
                stripped = f"{emoji} {raw_section}"
                feishu_lines.append(stripped)
                continue

        # 三级标题 (### ) 也加 emoji
        if stripped.startswith("### "):
            sub_section = stripped.replace("### ", "").strip()
            emoji = SECTION_EMOJI.get(sub_section, "")
            if emoji:
                stripped = f"  {emoji} {sub_section}"
            else:
                stripped = f"  🔹 {sub_section}"  # 默认 emoji

        # 隔夜行情速览 - 把表格转成文本
        if current_section == "一、隔夜行情速览":
            if "|" in stripped and ("昨收" in stripped or "|---" in stripped or "---|" in stripped or all(c == '|' for c in stripped.replace(' ', '').replace('-',''))):
                continue  # 跳过表头和分隔线
            if stripped.startswith("|") and ("🔺" in stripped or "🔻" in stripped or "—" in stripped or "伦敦" in stripped or "美元指数" in stripped or "布伦特" in stripped or "WTI" in stripped):
                cells = [c.strip() for c in stripped.split("|") if c.strip()]
                if len(cells) >= 4:
                    name = cells[0]
                    last = cells[1] if len(cells) > 1 else "-"
                    curr = cells[2] if len(cells) > 2 else "-"
                    change = cells[3] if len(cells) > 3 else "-"
                    gap = cells[4] if len(cells) > 4 else ""
                    gap_txt = f"（{gap}）" if gap and gap != "—" else ""
                    feishu_lines.append(f"**{name}**  {last} → {curr}  {change} {gap_txt}")
                    continue
            if stripped == "注：昨收为国内夜盘收盘时对应国际合约的结算价；最新价为当前国际现货/期货报价。":
                continue

        # 新闻概览 - 保留关键数据
        if current_section == "二、新闻概览":
            if stripped.startswith("- ") and "原始快讯" in stripped:
                continue
            if stripped.startswith("- ") and ("国内" in stripped or "国际" in stripped):
                continue

        # 重点新闻摘要 - 简化
        if current_section.startswith("三、重点新闻"):
            if stripped.startswith("- ") and "【" in stripped:
                # 去掉行首的 "- "
                clean = stripped[2:] if stripped.startswith("- ") else stripped
                # 提取内容
                match = re.search(r'【(.*?)】', clean)
                if match:
                    direction = match.group(1)
                    # 找标题部分
                    parts = clean.split("：")
                    title_text = parts[-1][:50] if len(parts) > 1 else clean[:50]
                    feishu_lines.append(f"• **{title_text}**（{direction}）")
                    continue

        # 回测验证板块 - 表格转文本
        if current_section == "回测验证":
            if "|" in stripped and ("昨开" in stripped or "资产" in stripped or "指标" in stripped or "---" in stripped):
                continue  # 跳过表头
            if stripped.startswith("|"):
                cells = [c.strip() for c in stripped.split("|") if c.strip()]
                # 整体准确率表 (2列)
                if len(cells) == 2 and cells[0] == "**整体准确率**":
                    feishu_lines.append(f"**整体准确率**: {cells[1]}")
                    continue
                if len(cells) == 2:
                    feishu_lines.append(f"  {cells[0]}: {cells[1]}")
                    continue
                # 各资产回测明细表 (7列)
                if len(cells) >= 7 and cells[0] not in ["", "-"]:
                    try:
                        name = cells[0]
                        o = cells[1]
                        c = cells[2]
                        chg = cells[3]
                        jdg = cells[4]
                        cor = cells[5]
                        acc = cells[6]
                        feishu_lines.append(f"**{name}**  {chg} | 判断{jdg}/{cor} = {acc}（开{o} 收{c}）")
                        continue
                    except:
                        pass

        # 今日关注因素
        if current_section == "今日关注因素":
            if "本报告期间市场关注" in stripped:
                feishu_lines.append("**市场关注方向：**")
                continue
            if "今日将公布的关注事件" in stripped:
                feishu_lines.append("")
                feishu_lines.append("**今日关注事件：**")
                continue
            if "需重点关注" in stripped:
                feishu_lines.append("")
                feishu_lines.append("**需重点关注：**")
                continue

        # 模型自我复盘 - 保留偏差提示
        if current_section == "模型自我复盘":
            if "以上偏差规则" in stripped or not stripped:
                continue

        # 跳过风险提示
        if current_section == "风险提示":
            continue

        # 其他内容原样保留
        feishu_lines.append(stripped)

    # 清理空行（最多保留一个连续空行）
    result = []
    prev_empty = False
    for l in feishu_lines:
        if not l:
            if prev_empty:
                continue
            prev_empty = True
        else:
            prev_empty = False
        result.append(l)

    return "\n".join(result)


def send_feishu(webhook_url, content, title):
    """发送到飞书群机器人（使用卡片消息，重新排版）"""
    if not webhook_url:
        return False

    # 重新排版为飞书友好格式
    feishu_content = format_for_feishu(content, title)

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title[:80]},
                "template": "blue"
            },
            "elements": [
                {"tag": "markdown", "content": feishu_content[:20000]},
                {"tag": "hr"},
                {"tag": "note", "elements": [
                    {"tag": "plain_text", "content": "📎 完整Excel数据已发至邮箱 | CommodityMorningBrief · 每日自动推送"}
                ]}
            ]
        }
    }
    data = json.dumps(card).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 0:
                print("  ✅ 飞书推送成功")
                return True
            else:
                print(f"  ⚠️  飞书推送失败: {result}")
                return False
    except Exception as e:
        print(f"  ⚠️  飞书推送异常: {e}")
        return False


def find_excel(date_str):
    """查找指定日期的 Excel 附件"""
    path = os.path.join(OUTPUT_DIR, f"commodity_news_{date_str}.xlsx")
    if os.path.exists(path):
        return path
    # fallback: 找最新的
    import glob
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "commodity_news_*.xlsx")), reverse=True)
    return files[0] if files else None


def parse_recipients(raw):
    return [item.strip() for item in raw.split(",") if item.strip()]


def send_email(title, plain_content, html_content, to_addrs=None, attachments=None):
    """通过 SMTP 发送 HTML 邮件，同时保留 text/plain，支持附件。"""
    smtp_host = get_config("SMTP_HOST")
    smtp_port = int(get_config("SMTP_PORT", "465"))
    smtp_user = get_config("SMTP_USER")
    smtp_password = get_config("SMTP_PASSWORD")
    smtp_from = get_config("SMTP_FROM") or smtp_user
    recipients = to_addrs or parse_recipients(get_config("SMTP_TO"))

    if not smtp_host or not smtp_from or not recipients:
        print("❌ 邮件配置不完整: 需要 SMTP_HOST、SMTP_FROM/SMTP_USER、SMTP_TO")
        return False
    if smtp_user and not smtp_password:
        print("❌ 邮件配置不完整: 已配置 SMTP_USER 但缺少 SMTP_PASSWORD")
        return False

    use_ssl = str_to_bool(get_config("SMTP_USE_SSL"), default=(smtp_port == 465))
    use_starttls = str_to_bool(get_config("SMTP_STARTTLS"), default=not use_ssl)

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = smtp_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(plain_content)
    msg.add_alternative(html_content, subtype="html")

    # 添加附件
    if attachments:
        for fpath in attachments:
            if not fpath or not os.path.exists(fpath):
                continue
            fname = os.path.basename(fpath)
            with open(fpath, "rb") as f:
                file_data = f.read()
            # 根据扩展名推断 MIME 类型
            if fname.endswith(".xlsx"):
                maintype, subtype = "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            elif fname.endswith(".pdf"):
                maintype, subtype = "application", "pdf"
            else:
                import mimetypes
                maintype, subtype = (mimetypes.guess_type(fname)[0] or "application/octet-stream").split("/", 1)
            msg.add_attachment(file_data, maintype=maintype, subtype=subtype, filename=fname)
            print(f"   📎 附件: {fname} ({len(file_data)} bytes)")

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=20)
        with server:
            if use_starttls and not use_ssl:
                server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        print(f"✅ HTML 邮件发送成功: {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"❌ HTML 邮件发送失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="CommodityMorningBrief PushPlus 推送")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y%m%d"),
                        help="报告日期 YYYYMMDD")
    parser.add_argument("--title", type=str, default="",
                        help="推送标题, 默认: CommodityMorningBrief 每日简报")
    parser.add_argument("--to", type=str, default="",
                        help="PushPlus token (暂存)")
    parser.add_argument("--email", action="store_true",
                        help="同时发送 HTML 邮件")
    parser.add_argument("--email-to", type=str, default="",
                        help="邮件收件人, 多个邮箱用英文逗号分隔；默认读取 SMTP_TO")
    parser.add_argument("--no-push", action="store_true",
                        help="不发送 PushPlus, 只执行其它通道")

    args = parser.parse_args()

    if args.to:
        os.environ["PUSHPLUS_TOKEN"] = args.to

    title = args.title or f"CommodityMorningBrief 每日简报 - {args.date}"
    content = build_report_content(args.date)

    # 截取前 2000 字符 (PushPlus 限制)
    preview = content[:2000]

    print(f"📤 准备推送: {title}")
    print(f"   内容长度: {len(content)} 字符 (截取前 {len(preview)} 发送)")
    print()

    if not args.no_push:
        send_push(title, preview, template="markdown")

    # 飞书推送
    feishu_url = get_config("FEISHU_WEBHOOK_URL")
    if feishu_url:
        send_feishu(feishu_url, content, title)

    if args.email:
        recipients = parse_recipients(args.email_to) if args.email_to else None
        html_content = markdown_to_html(content, title)
        # 查找 Excel 附件
        excel_path = find_excel(args.date)
        attachments = [excel_path] if excel_path else None
        send_email(title, content, html_content, recipients, attachments=attachments)

    print()
    print("💡 微信/PushPlus 保留 Markdown 文本；邮件使用 HTML + 纯文本双版本")


if __name__ == "__main__":
    main()
