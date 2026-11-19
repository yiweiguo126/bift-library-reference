#!/usr/bin/env python3
"""现取北服图书馆「本馆概况 / 机构设置 / 服务项目」三页的最新正文。

三页均从授权起点 S2-1 站内导航下钻定位，与「空间服务」同实例，正文在
generalDataType.introduction，表格结构由本脚本转成对齐的 Markdown 表格照录。
登记信息（2026-11-16，详见 SKILL.md「馆情信息动态接口路由」）：
    about    本馆概况   typeId=5695087
    org      机构设置   typeId=5695088
    service  服务项目   typeId=5695099

共同接口与参数：
    GET https://lib.bift.edu.cn/engine2/general/1690193/more/detail
    engineInstanceId=2412452 & typeId=<见上> & sw= & sign=<运行时从栏目页 var sign 动态读取>

sign 随站点改版变化，每次运行复用 fetch_resource_list.read_sign() 从栏目页动态读取，
读不到才回退登记常量 sign_fallback（原 e1c07d97d45eccffc1e99fff0be5699b 已失效）。
本脚本只打印到标准输出，不写文件、不缓存：每次运行都取馆方当前最新版本。

用法：
    python3 scripts/fetch_library_info.py --page about
    python3 scripts/fetch_library_info.py --page org
    python3 scripts/fetch_library_info.py --page service
    python3 scripts/fetch_library_info.py --page all       # 取全部 3 页，仅供核对，不用于单次作答
    python3 scripts/fetch_library_info.py --page org --sign ""   # 站点改版后覆盖参数
"""

import argparse
import datetime
import html as html_mod
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import fetch_resource_list as rl  # 复用其 read_sign()：栏目页动态读 sign

SITE = "https://lib.bift.edu.cn"
COMMON = {
    "appId": "1690193",
    "engineInstanceId": "2412452",
    "sign": "e1c07d97d45eccffc1e99fff0be5699b",  # 登记常量（旧值，仅兜底）
}
PAGES = {
    "about": {
        "label": "本馆概况",
        "type_id": "5695087",
        "column": (
            SITE + "/engine2/general/more?t="
            "C4740E6911E404EAA1EAC58C094FE3B4B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4"
        ),
    },
    "org": {
        "label": "机构设置",
        "type_id": "5695088",
        "column": (
            SITE + "/engine2/general/more?t="
            "C4740E6911E404EA02DF3C2B5EECB126B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4"
        ),
    },
    "service": {
        "label": "服务项目",
        "type_id": "5695099",
        "column": (
            SITE + "/engine2/general/more?t="
            "4F3712F2DAA72EB2274F5C90523EDDA3B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4"
        ),
    },
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def fetch(params, column_url, timeout):
    endpoint = f"{SITE}/engine2/general/{params['appId']}/more/detail"
    query = urllib.parse.urlencode(
        {
            "engineInstanceId": params["engineInstanceId"],
            "typeId": params["typeId"],
            "sw": "",
            "sign": params["sign"],
        }
    )
    url = endpoint + "?" + query
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": column_url})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"取页失败：{exc}\n接口：{url}")
    if len(raw) < 1000:
        raise SystemExit(f"接口返回异常（{len(raw)} B），可能分类 ID 已失效：{url}")
    return url, raw


def decode_unicode_escapes(raw):
    """响应里中文以 \\uXXXX 转义，先还原为明文。"""
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), raw)


def extract_introduction(decoded, fallback_title):
    m = re.search(r'"introduction"\s*:\s*"((?:\\.|[^"\\])*)"', decoded)
    if not m:
        raise SystemExit("未在响应中找到 introduction 字段，接口结构可能已改版")
    try:
        intro = json.loads('"' + m.group(1) + '"')
    except json.JSONDecodeError as exc:
        raise SystemExit(f"introduction 字段解码失败：{exc}")
    # 响应前面有若干空 name 字段，取第一个非空名称（generalDataType.name）
    names = re.findall(r'"name"\s*:\s*"([^"]+)"', decoded)
    return (names[0] if names else fallback_title), intro


def clean_cell(fragment):
    """单元格内文本：去掉标签、合并空白，单元格内多段用 <br> 相连。"""
    s = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    s = re.sub(r"</(p|div|li|h[1-6])>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s)
    s = s.replace("\xa0", " ").replace("\u200b", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def html_to_text(fragment):
    """非表格段落按原段落转文本，表格转 Markdown 表格（照录单元格文字，不改写）。"""
    pieces = []
    pos = 0
    for tm in re.finditer(r"<table\b.*?</table>", fragment, flags=re.I | re.S):
        pieces.append(("text", fragment[pos:tm.start()]))
        pieces.append(("table", tm.group(0)))
        pos = tm.end()
    pieces.append(("text", fragment[pos:]))

    out = []
    for kind, chunk in pieces:
        if kind == "text":
            s = re.sub(r"<br\s*/?>", "\n", chunk, flags=re.I)
            s = re.sub(r"</(p|div|tr|h[1-6]|li)>", "\n", s, flags=re.I)
            s = re.sub(r"<[^>]+>", "", s)
            s = html_mod.unescape(s).replace("\xa0", " ").replace("\u200b", "")
            s = re.sub(r"[ \t]+", " ", s)
            s = re.sub(r"\n[ \t]+", "\n", s)
            s = re.sub(r"\n{2,}", "\n", s).strip()
            if s:
                out.append(s)
        else:
            rows = []
            for rm in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", chunk, flags=re.I | re.S):
                cells = [
                    clean_cell(cm.group(1))
                    for cm in re.finditer(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", rm.group(1), flags=re.I | re.S)
                ]
                if cells:
                    rows.append(cells)
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                table_lines = ["| " + " | ".join(rows[0]) + " |",
                               "|" + "|".join(["---"] * width) + "|"]
                table_lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                out.append("\n".join(table_lines))
    return "\n\n".join(out).strip()


def extract_images(fragment):
    urls = []
    for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', fragment, flags=re.I):
        src = src.replace("\\/", "/")
        absolute = urllib.parse.urljoin(SITE, src)
        if absolute not in urls:
            urls.append(absolute)
    return urls


def render(page_key, args):
    page = PAGES[page_key]
    params = dict(COMMON, typeId=args.type_id or page["type_id"])
    url, raw = fetch(params, page["column"], args.timeout)
    decoded = decode_unicode_escapes(raw)
    title, intro = extract_introduction(decoded, page["label"])
    text = html_to_text(intro)
    images = extract_images(intro)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"# {title}（接口现取，{now}）")
    print()
    print(f"- 栏目页：{page['column']}")
    print(f"- 实际取回接口：{url}")
    print(f"- sign：{'运行时从栏目页读取' if COMMON.get('sign_from_page') else '登记常量／命令行指定（若接口报错请核对栏目页 var sign）'}")
    print("- 取回方式：GET（服务端返回 Unicode 转义 HTML，本脚本已解码并提取 introduction，表格转 Markdown 照录）")
    print()
    print("## 正文（照录，未改写）")
    print()
    print(text)
    print()
    print(f"## 图片 URL（共 {len(images)} 张，均为 lib.bift.edu.cn 同源，可访问）")
    for i, img in enumerate(images, 1):
        print(f"{i}. {img}")
    if not images:
        print("（本次页面无图片）")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--page", choices=list(PAGES) + ["all"], default="about",
                    help="取哪个馆情信息页；all=三页全取，仅供核对，不用于单次作答")
    ap.add_argument("--app-id", default=COMMON["appId"])
    ap.add_argument("--engine-instance-id", default=COMMON["engineInstanceId"])
    ap.add_argument("--type-id", default=None,
                    help="覆盖分类 ID；默认按 --page 自动选择，三个页面的 ID 见文件头注释")
    ap.add_argument("--sign", default=COMMON["sign"],
                    help="实测可为空；站点改版后从栏目页 var sign 重新读取")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()
    COMMON["appId"] = args.app_id
    COMMON["engineInstanceId"] = args.engine_instance_id
    # sign 动态读取（站点改版会失效）；仅当用户未显式用 --sign 覆盖时启用
    if args.sign == COMMON["sign"]:
        dyn_sign, from_page = rl.read_sign(args.timeout)
        COMMON["sign"] = dyn_sign
        args.sign = dyn_sign
    else:
        from_page = False
    COMMON["sign_from_page"] = from_page

    keys = list(PAGES) if args.page == "all" else [args.page]
    for i, key in enumerate(keys):
        if i:
            print("\n\n" + "=" * 60 + "\n")
        render(key, args)


if __name__ == "__main__":
    main()
