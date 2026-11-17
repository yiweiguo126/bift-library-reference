#!/usr/bin/env python3
"""现取北服图书馆「数字资源」条目详情页正文（静态可解析，无需渲染、无需浏览器）。

结论依据（2026-11-17 实测）：详情页 /engine2/d/<dataId>/<instanceId>/0 的正文
并非 XHR 拉取，而是**内嵌在页面内联 <script> 的 Vue data 里**，字段为
    data: { "engineInstanceId":..., "content":"<p ...>…</p>", ... }
因此去掉标签后即可得到与浏览器所见一致的正文；此前「必须渲染」的判断是误解——
按 HTML 标签剥文本时连 <script> 块一起删掉了，才误以为页面只有框架。

用法：
    python3 scripts/fetch_resource_detail.py --url "<详情页 URL>"     # 从清单输出里取的地址
    python3 scripts/fetch_resource_detail.py --data-id 11103910       # 只给 dataId（默认实例 2639617）
    python3 scripts/fetch_resource_detail.py --search 元阅读          # 清单匹配 → 自动取该条正文（默认 trial）
    python3 scripts/fetch_resource_detail.py --search 元阅读 --type feature
    python3 scripts/fetch_resource_detail.py --url "..." --html       # 同时打印原始 HTML 片段
    python3 scripts/fetch_resource_detail.py --url "..." --json       # 结构化输出

取文失败时退出码 3，按 SKILL.md「入口式回答」给清单页与详情页链接，不猜、不拼。
"""

import argparse
import html as html_mod
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://lib.bift.edu.cn"
DEFAULT_INSTANCE = "2639617"
PAGE_ID = "331274"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "Chrome/120.0 Safari/537.36"
)
BLOCK_TAGS = (
    "p|div|br|tr|li|ul|ol|table|tbody|thead|h1|h2|h3|h4|h5|h6|section|article|blockquote"
)


def get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"取页失败：{exc}\n页面：{url}")


def detail_url(data_id, instance=DEFAULT_INSTANCE):
    return f"{SITE}/engine2/d/{data_id}/{instance}/0?p={PAGE_ID}"


def _read_js_string(buf, quote_index):
    """从 JS 字符串字面量的开引号处读到收引号，返回解码后的 Python 字符串。"""
    k = quote_index + 1
    out = []
    while k < len(buf):
        ch = buf[k]
        if ch == "\\":
            out.append(buf[k : k + 2])
            k += 2
            continue
        if ch == '"':
            break
        out.append(ch)
        k += 1
    try:
        return json.loads('"' + "".join(out) + '"')
    except json.JSONDecodeError:
        return None


def extract_content(page_html):
    """在内联 <script> 中定位 Vue data 的 content 字段，返回 (content_html, 诊断信息)。"""
    blocks = re.findall(
        r"<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>", page_html, re.I
    )
    best = None
    for block in blocks:
        if '"content"' not in block:
            continue
        for m in re.finditer(r'"content"\s*:\s*"', block):
            val = _read_js_string(block, m.end() - 1)
            if not val:
                continue
            # 同一页可能有多个 content（如导航块），取最长的一段
            if best is None or len(val) > len(best):
                best = val
    if best is None:
        return None, f"页面 {len(page_html)} 字节，未在内联脚本中找到 content 字段"
    return best, None


def to_text(content_html):
    """HTML → 纯文本，保留段落与列表层级感；图片以［图片］占位。"""
    s = re.sub(r"<img\b[^>]*>", "\n［图片］\n", content_html, flags=re.I)
    s = re.sub(r"<li\b[^>]*>", "\n· ", s, flags=re.I)
    s = re.sub(r"</(?:%s)\s*>" % BLOCK_TAGS, "\n", s, flags=re.I)
    s = re.sub(r"<(?:%s)\b[^>]*>" % BLOCK_TAGS, "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    lines = [ln for ln in lines if ln]
    # 连续的空段落已在上面被过滤；此处仅合并孤立的「·」前缀行
    return "\n".join(lines), lines


def locate_by_keyword(keyword, type_key, timeout):
    """调用同目录清单脚本的取数与匹配逻辑，返回 (标题, 发布时间, dataId, 详情页 URL)。"""
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import fetch_resource_list as rl
    except ImportError:
        raise SystemExit("未找到同目录的 fetch_resource_list.py，无法按关键词定位条目")

    sign, _ = rl.read_sign(timeout)
    label, type_id = rl.TYPES[type_key]
    items, total, _, err = rl.fetch_items(type_id, 1, 100, sign, timeout)
    if err:
        raise SystemExit(f"{label}清单接口异常，未取到条目：{err}")
    hits = [it for it in items if keyword in rl.title_of(it)]
    if not hits:
        raise SystemExit(
            f"{label}清单（共 {total} 条）中未匹配到「{keyword}」，"
            "按 SKILL.md 处理：可答为不在该清单，不反推从未有过"
        )
    it = hits[0]
    data_id, durl = rl.detail_of(it)
    if not data_id:
        raise SystemExit(
            f"「{rl.title_of(it)}」无站内详情页（可能为站外入口），照录名称即可、不访问"
        )
    return rl.title_of(it), rl.time_of(it), data_id, durl or detail_url(data_id)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="详情页完整 URL（从 fetch_resource_list.py 输出复制）")
    ap.add_argument("--data-id", help="详情页 dataId（数字）")
    ap.add_argument("--instance", default=DEFAULT_INSTANCE, help="引擎实例 ID，默认 2639617")
    ap.add_argument("--search", help="按关键词在清单中定位条目后取正文（默认试用资源）")
    ap.add_argument(
        "--type",
        default="trial",
        choices=["common", "feature", "trial"],
        help="--search 时使用的清单类别：common／feature／trial（默认）",
    )
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--html", action="store_true", help="附加打印原始正文 HTML 片段")
    ap.add_argument("--json", action="store_true", help="结构化输出")
    args = ap.parse_args()

    if not (args.url or args.data_id or args.search):
        ap.error("请指定 --url、--data-id 或 --search 之一")

    title = time_str = None
    if args.search:
        title, time_str, data_id, url = locate_by_keyword(
            args.search, args.type, args.timeout
        )
    else:
        url = args.url or detail_url(args.data_id, args.instance)
        m = re.search(r"/engine2/d/(\d+)/", url)
        data_id = m.group(1) if m else args.data_id

    page = get(url, args.timeout)
    content, err = extract_content(page)
    if not content:
        if args.json:
            print(json.dumps({"ok": False, "url": url, "data_id": data_id, "error": err}, ensure_ascii=False, indent=1))
        else:
            print("# 资源详情页正文取文失败")
            print(f"- 详情页：{url}")
            print(f"- 原因：{err}")
            print("- 处置：按「入口式回答」给条目名＋清单页与详情页链接，说明正文未取到；不猜、不用清单字段代替正文。")
        sys.exit(3)

    text, lines = to_text(content)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "title": title,
                    "published": time_str,
                    "data_id": data_id,
                    "url": url,
                    "line_count": len(lines),
                    "text": text,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return

    print("# 资源详情页正文（静态取文，计 1 页）")
    if title:
        print(f"- 条目：{title}" + (f"｜发布时间：{time_str}" if time_str else ""))
    print(f"- dataId：{data_id}")
    print(f"- 详情页：{url}")
    print("- 来源：页面内联脚本 data.content（与浏览器所见一致，无需渲染）")
    print()
    print(text)
    if args.html:
        print()
        print("--- 原始 HTML 片段 ---")
        print(content[:2000])
    imgs = len(re.findall(r"<img\b", content, re.I))
    if imgs:
        print()
        print(f"注：正文含 {imgs} 张图片（如二维码、操作截图），已以［图片］占位；图片内文字不可照录，涉及图片内容时提示读者按详情页查看。")


if __name__ == "__main__":
    main()
