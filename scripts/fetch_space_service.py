#!/usr/bin/env python3
"""现取北服图书馆「空间服务」下动态栏目页的最新正文与图片 URL。

已登记页面（2026-11-16 定位，详见 SKILL.md「空间服务动态接口路由」）：
    open_time 开放时间       typeId=5695048
    yanxue    研学空间预约   typeId=5695077
    seat      座位预约       typeId=5695067
    locker    存包柜预约     typeId=5695068
    quiet     静音舱预约     typeId=6021280

共同接口与参数：
    GET https://lib.bift.edu.cn/engine2/general/1690193/more/detail
    engineInstanceId=2412452 & typeId=<见上> & sw= & sign=<运行时从栏目页 var sign 动态读取>

sign 随站点改版变化，每次运行复用 fetch_resource_list.read_sign() 从栏目页动态读取，
读不到才回退登记常量 sign_fallback（原 e1c07d97d45eccffc1e99fff0be5699b 已失效，
2026-11-19 实测接口报 mh_engine_50004；动态值为 ab6aac2c173b005b0611492779d7e542）。
响应正文以 \\uXXXX 转义的 JS 对象返回，正文 HTML 在 generalDataType.introduction。
本脚本只打印到标准输出，不写文件、不缓存：每次运行都取馆方当前最新版本。

用法：
    python3 scripts/fetch_space_service.py --page seat
    python3 scripts/fetch_space_service.py --page quiet
    python3 scripts/fetch_space_service.py --page all       # 取全部 5 页，仅供核对，不用于单次作答
    python3 scripts/fetch_space_service.py --page seat --sign ""   # 站点改版后覆盖参数
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
    "yanxue": {
        "label": "研学空间预约",
        "type_id": "5695077",
        "column": (
            SITE + "/engine2/general/more?t="
            "90A48DC6A57EFA7BA1EAC58C094FE3B4B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4"
        ),
    },
    "open_time": {
        "label": "开放时间",
        "type_id": "5695048",
        "column": (
            SITE + "/engine2/general/more?t="
            "67355CA0454F531402DF3C2B5EECB126B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4"
        ),
    },
    "seat": {
        "label": "座位预约",
        "type_id": "5695067",
        "column": (
            SITE + "/engine2/general/more?t="
            "EB947627087CEFC2A1EAC58C094FE3B4B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4"
        ),
    },
    "locker": {
        "label": "存包柜预约",
        "type_id": "5695068",
        "column": (
            SITE + "/engine2/general/more?t="
            "EB947627087CEFC202DF3C2B5EECB126B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4"
        ),
    },
    "quiet": {
        "label": "静音舱预约",
        "type_id": "6021280",
        "column": (
            SITE + "/engine2/general/more?t="
            "97F4FBCDB16764C03954CFAA8E124E88B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4"
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
    name_m = re.search(r'"name"\s*:\s*"([^"]+)"', decoded)
    return (name_m.group(1) if name_m else fallback_title), intro


def html_to_text(fragment):
    """按原段落/表格行转文本：单元格用 | 分隔，保留原句文字，不改写。"""
    s = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    s = re.sub(r"</(p|div|tr|h[1-6]|li)>", "\n", s, flags=re.I)
    s = re.sub(r"</(td|th)>", " | ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s)
    s = s.replace("\u200b", "")  # 零宽空格
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


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
    print("- 取回方式：GET（服务端返回 Unicode 转义 HTML，本脚本已解码并提取 introduction）")
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
    ap.add_argument("--page", choices=list(PAGES) + ["all"], default="yanxue",
                    help="取哪个空间服务栏目；all=五页全取，仅供核对，不用于单次作答")
    ap.add_argument("--app-id", default=COMMON["appId"])
    ap.add_argument("--engine-instance-id", default=COMMON["engineInstanceId"])
    ap.add_argument("--type-id", default=None,
                    help="覆盖分类 ID；默认按 --page 自动选择，五个页面的 ID 见文件头注释")
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
