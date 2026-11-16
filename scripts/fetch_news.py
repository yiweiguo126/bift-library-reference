#!/usr/bin/env python3
"""现取北服图书馆「最新资讯」栏目（时效性内容：节假日/寒暑假开馆安排、
最新服务介绍、存包柜预约结果等）。该栏目 2026-11-16 登记，详见 SKILL.md
「最新资讯动态接口路由」节。

栏目页：https://lib.bift.edu.cn/engine2/m/037D40C8DF9A6148?p=331274
本栏目实例参数与空间/学研/资源/借阅四组不同，特指：
    appId=1799821  engineInstanceId=2570405  typeId=5688533
    sign=3d73194df645a2ef3a5632e7d6fb1a87
列表接口（返回 419 条 / 5 页，按发布时间倒序，含标题的 key=1 与发布时间的 key=6）：
    GET https://lib.bift.edu.cn/engine2/general/1799821/type/more-clear-datas
    engineInstanceId=2570405 & typeId=5688533 & pageNum=<N> & pageSize=100
    & sign=... & websiteId=186080 & pageId=331274 & wfwfid=33400
条目正文接口（与列表同一 detail 端点，带 generalDataId）：
    GET https://lib.bift.edu.cn/engine2/general/1799821/more/detail
    engineInstanceId=2570405 & typeId=5688533 & sw= & sign=... & generalDataId=<条目 id>
响应正文以 \\uXXXX 转义，中文须先解码；列表标题在条目的 "1".value，
发布时间在 "6".value，正文在 generalDataType.content / generalData.content。
脚本只打印到标准输出，不写文件、不缓存。

用法：
    python3 scripts/fetch_news.py --list                    # 取列表第 1 页（最新 100 条标题+时间+id）
    python3 scripts/fetch_news.py --list --page-num 2       # 取列表第 2 页
    python3 scripts/fetch_news.py --search 国庆              # 标题匹配，列出命中条目（不取正文）
    python3 scripts/fetch_news.py --data-id 11104062        # 取指定条目正文
    python3 scripts/fetch_news.py --search 国庆 --data-id 11104062  # 标注命中后取该条正文
"""

import argparse
import datetime
import html as html_mod
import json
import re
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://lib.bift.edu.cn"
NEWS = {
    "label": "最新资讯",
    "app_id": "1799821",
    "engine_instance_id": "2570405",
    "type_id": "5688533",
    "sign": "3d73194df645a2ef3a5632e7d6fb1a87",
    "website_id": "186080",
    "page_id": "331274",
    "wfwfid": "33400",
    "column": SITE + "/engine2/m/037D40C8DF9A6148?p=331274",
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": SITE})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"取页失败：{exc}\n接口：{url}")


def decode(raw):
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), raw)


def field(decoded, name):
    m = re.search(r'"' + re.escape(name) + r'"\s*:\s*"((?:\\.|[^"\\])*)"', decoded)
    if not m:
        return None
    try:
        return json.loads('"' + m.group(1) + '"')
    except json.JSONDecodeError:
        return None


def html_to_text(fragment):
    s = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    s = re.sub(r"</(p|div|tr|h[1-6]|li)>", "\n", s, flags=re.I)
    s = re.sub(r"</(td|th)>", " | ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s).replace("\xa0", " ").replace("\u200b", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


def extract_images(fragment):
    urls = []
    for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', fragment, flags=re.I):
        absolute = urllib.parse.urljoin(SITE, src.replace("\\/", "/"))
        if absolute not in urls:
            urls.append(absolute)
    return urls


def list_url(page_num):
    q = {
        "engineInstanceId": NEWS["engine_instance_id"],
        "typeId": NEWS["type_id"],
        "pageNum": page_num,
        "pageSize": 100,
        "sign": NEWS["sign"],
        "websiteId": NEWS["website_id"],
        "pageId": NEWS["page_id"],
        "wfwfid": NEWS["wfwfid"],
    }
    return f"{SITE}/engine2/general/{NEWS['app_id']}/type/more-clear-datas?" + urllib.parse.urlencode(q)


def detail_url(data_id):
    q = {
        "engineInstanceId": NEWS["engine_instance_id"],
        "typeId": NEWS["type_id"],
        "sw": "",
        "sign": NEWS["sign"],
        "generalDataId": data_id,
    }
    return f"{SITE}/engine2/general/{NEWS['app_id']}/more/detail?" + urllib.parse.urlencode(q)


def fetch_list(page_num, timeout):
    raw = get(list_url(page_num), timeout)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return [], None, None
    # 接口异常时 data/datas 可能为 null，逐层判断避免 None.get
    if not isinstance(obj, dict):
        return [], None, None
    data = obj.get("data")
    if not isinstance(data, dict):
        return [], None, None
    node = data.get("datas")
    if not isinstance(node, dict):
        return [], None, None
    items = node.get("datas", [])
    return (items if isinstance(items, list) else []), node.get("totalPage"), node.get("totalRecords")


def item_title(it):
    return it.get("1", {}).get("value", "") or ""


def item_time(it):
    return it.get("6", {}).get("value", "") or ""


def print_list(items, total_page, total_records, page_num):
    print(f"# 最新资讯·列表（第 {page_num} 页／共 {total_page} 页，全部 {total_records} 条）")
    print()
    print(f"- 栏目页：{NEWS['column']}")
    print(f"- 实际取回接口：{list_url(page_num)}")
    print("- 说明：按发布时间倒序；标题取自条目「标题」字段，时间为「发布时间」字段")
    print()
    for i, it in enumerate(items, 1):
        print(f"{i:3d}. {item_time(it)}｜{item_title(it) or '（无标题）'}｜dataId={it.get('id')}")
    if not items:
        print("（本页无条目）")


def print_detail(data_id, timeout, args):
    durl = detail_url(data_id)
    decoded = decode(get(durl, timeout))
    content = field(decoded, "content") or field(decoded, "introduction") or ""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"# 最新资讯·条目正文（dataId={data_id}，接口现取，{now}）")
    print()
    print(f"- 栏目页：{NEWS['column']}")
    print(f"- 条目详情页（可点开）：{SITE}/engine2/d/{data_id}/{NEWS['engine_instance_id']}/0?t={NEWS['type_id']}&p={NEWS['page_id']}")
    print(f"- 实际取回接口：{durl}")
    print("- 取回方式：GET（服务端返回 Unicode 转义 HTML，本脚本已解码并提取正文）")
    print()
    if content:
        print("## 正文（照录，未改写）")
        print()
        print(html_to_text(content))
    else:
        print("## 正文（照录，未改写）")
        print()
        print("（本条 content/introduction 为空；不以标题或列表字段代替正文）")
    imgs = extract_images(content)
    print()
    print(f"## 图片 URL（共 {len(imgs)} 张，均为 lib.bift.edu.cn 同源）")
    for i, img in enumerate(imgs, 1):
        print(f"{i}. {img}")
    if not imgs:
        print("（本条无图片）")
    if args.search:
        print()
        print(f"## 标题匹配关键词：{args.search}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="取列表（默认第 1 页最新 100 条）")
    ap.add_argument("--page-num", type=int, default=1, help="列表页码，默认 1")
    ap.add_argument("--search", help="按标题关键词筛选列表（不取正文，除非同时给 --data-id）")
    ap.add_argument("--data-id", help="取指定条目的正文")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()
    if not (args.list or args.search or args.data_id):
        ap.error("请指定 --list、--search 或 --data-id 之一")

    if args.search or (args.data_id and not args.list):
        items, total_page, total_records = fetch_list(1, args.timeout)
        if args.search:
            hits = [it for it in items if args.search in item_title(it)]
            print(f"# 最新资讯·标题匹配「{args.search}」（第 1 页，共 {len(items)} 条中命中 {len(hits)} 条）")
            print()
            print(f"- 栏目页：{NEWS['column']}")
            print(f"- 列表接口：{list_url(1)}")
            print(f"- 全部条目：{total_records} 条 / {total_page} 页；本页为最新 100 条，未命中可翻页 --list --page-num N")
            print()
            for i, it in enumerate(hits, 1):
                print(f"{i}. {item_time(it)}｜{item_title(it)}｜dataId={it.get('id')}")
                print(f"   详情页：{SITE}/engine2/d/{it.get('id')}/{NEWS['engine_instance_id']}/0?t={NEWS['type_id']}&p={NEWS['page_id']}")
                print(f"   取正文：python3 scripts/fetch_news.py --data-id {it.get('id')}")
            if not hits:
                print("（第 1 页未命中；较旧条目请用 --list --page-num 2/3/4/5 查找）")
            if args.data_id and hits:
                print()
                print("=" * 60)
                print()
        if args.data_id:
            print_detail(args.data_id, args.timeout, args)
        return

    if args.list:
        items, total_page, total_records = fetch_list(args.page_num, args.timeout)
        print_list(items, total_page, total_records, args.page_num)


if __name__ == "__main__":
    main()
