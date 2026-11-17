#!/usr/bin/env python3
"""现取北服图书馆「数字资源」三类清单：常用资源、特色资源、试用资源。

用途：提问涉及某个具体数据库／资源，但在 SKILL.md「已登记资源详情页」表中
未命中（新增资源、试用资源、已下架资源判断）时，先用本脚本确认该资源当前
是否在清单内、拿到它的详情页地址。清单随资源调整变动，不固化、不缓存。

2026-11-17 实测（馆员核对用）：
    常用资源  typeId=5926874   该 typeId 直挂 1 条，其余条目分属其子分类
    特色资源  typeId=5695011   9 条（自建库）
    试用资源  typeId=6021282   10 条，随试用开通／到期上下架

栏目页（S2-2，作为参数来源与出处）：
    https://lib.bift.edu.cn/engine2/general/more?t=1657C515DE78950722E9EA3A83EA366AB7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4

列表接口：
    GET https://lib.bift.edu.cn/engine2/general/1690193/type/more-clear-datas
        engineInstanceId=2412452 & typeId=<分类ID> & pageNum=<N> & pageSize=100
        & sign=<栏目页 var sign> & websiteId=186080 & pageId=331274 & wfwfid=33400
    条目标题在 "1".value，发布时间在 "6".value，简介 "4".value 一般为空；
    条目 url 字段内含真正的详情页 /engine2/d/<dataId>/2639617/0（dataId 与条目 id 不同，
    必须从返回值取，不得自行拼接）。

重要：资源详情页正文由页面脚本渲染后加载，静态取回只有导航框架与模板残留。
本脚本只负责清单与详情页地址，不打印正文。需要正文时按 SKILL.md
「资源清单动态接口路由」办理：能渲染则照录，渲染不可用则走入口式回答。

用法：
    python3 scripts/fetch_resource_list.py --list                    # 试用资源清单（默认 trial）
    python3 scripts/fetch_resource_list.py --list --type feature     # 特色资源清单
    python3 scripts/fetch_resource_list.py --search 元阅读          # 关键词匹配（试用资源）
    python3 scripts/fetch_resource_list.py --search 元阅读 --type trial
    python3 scripts/fetch_resource_list.py --type all               # 三类一并列出（仅供馆员核对）
"""

import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://lib.bift.edu.cn"
COMMON = {
    "app_id": "1690193",
    "engine_instance_id": "2412452",
    "website_id": "186080",
    "page_id": "331274",
    "wfwfid": "33400",
    "sign_fallback": "2896b1accc39ab931295bb7137ea6342",
}
COLUMN = (
    SITE
    + "/engine2/general/more?t=1657C515DE78950722E9EA3A83EA366AB7DDA59FFDFE902744EC8E2CF639EB6"
    "3BE8DADE456461C9250A88391EF6FCAF4"
)
TYPES = {
    "common": ("常用资源", "5926874"),
    "feature": ("特色资源", "5695011"),
    "trial": ("试用资源", "6021282"),
}
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "Chrome/120.0 Safari/537.36"
)


def get(url, timeout, referer=COLUMN):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"取页失败：{exc}\n接口：{url}")


def read_sign(timeout):
    """sign 随站点改版变化，每次运行先读栏目页 var sign；读不到用登记常量。"""
    try:
        page = get(COLUMN, timeout)
    except SystemExit:
        return COMMON["sign_fallback"], False
    m = re.search(r'var\s+sign\s*=\s*"([0-9a-f]{32})"', page)
    if not m:
        return COMMON["sign_fallback"], False
    return m.group(1), True


def list_url(type_id, page_num, page_size, sign):
    q = {
        "engineInstanceId": COMMON["engine_instance_id"],
        "typeId": type_id,
        "pageNum": page_num,
        "pageSize": page_size,
        "sign": sign,
        "websiteId": COMMON["website_id"],
        "pageId": COMMON["page_id"],
        "wfwfid": COMMON["wfwfid"],
    }
    return (
        f"{SITE}/engine2/general/{COMMON['app_id']}/type/more-clear-datas?"
        + urllib.parse.urlencode(q)
    )


def fetch_items(type_id, page_num, page_size, sign, timeout):
    raw = get(list_url(type_id, page_num, page_size, sign), timeout)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return [], None, None, raw[:200]
    data = obj.get("data") if isinstance(obj, dict) else None
    node = data.get("datas") if isinstance(data, dict) else None
    if not isinstance(node, dict):
        return [], None, None, raw[:200]
    items = node.get("datas") or []
    return (
        items if isinstance(items, list) else [],
        node.get("totalRecords"),
        node.get("totalPage"),
        None,
    )


def title_of(it):
    return (it.get("1") or {}).get("value", "") or ""


def time_of(it):
    return (it.get("6") or {}).get("value", "") or ""


def detail_of(it):
    """从条目 url 字段取详情页地址；dataId 与条目 id 不同，只能取自返回值。"""
    raw = urllib.parse.unquote(it.get("url") or "")
    m = re.search(r"/engine2/d/(\d+)/", raw)
    if not m:
        return None, None
    data_id = m.group(1)
    return data_id, f"{SITE}/engine2/d/{data_id}/2639617/0?p={COMMON['page_id']}"


def print_block(label, type_id, items, total_records, total_page, url, matched=None):
    head = f"# 数字资源·{label}清单"
    if matched is not None:
        head += f"（标题匹配「{matched}」，共 {len(items)} 条命中）"
    print(head + f"｜清单总数 {total_records} 条／{total_page} 页")
    print()
    print(f"- 栏目页（可点开，读者自行打开即可看到本清单）：{COLUMN}")
    print(f"- 实际取回接口：{url}")
    print("- 说明：清单随资源上下架变动；条目发布时间为馆方上架时间，不等于试用起止日期")
    print()
    if not items:
        print("（无条目）")
        print()
        return
    for i, it in enumerate(items, 1):
        data_id, durl = detail_of(it)
        print(f"{i:3d}. {time_of(it)}｜{title_of(it) or '（无标题）'}")
        if durl:
            print(f"     详情页：{durl}")
            print(f"     dataId={data_id}")
        else:
            print("     详情页：（本条无站内详情页，可能为站外入口，照录名称即可、不访问）")
    print()
    print("注：详情页正文需在浏览器中渲染后取；脚本不打印正文，取不到即按入口式回答给上列链接。")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="列出清单（默认试用资源）")
    ap.add_argument("--search", help="按条目标题关键词筛选（默认试用资源）")
    ap.add_argument(
        "--type",
        default="trial",
        choices=["common", "feature", "trial", "all"],
        help="清单类别：common 常用／feature 特色／trial 试用（默认）／all 三类并列",
    )
    ap.add_argument("--page-num", type=int, default=1)
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()
    if not (args.list or args.search):
        ap.error("请指定 --list 或 --search 之一")

    sign, from_page = read_sign(args.timeout)
    keys = list(TYPES) if args.type == "all" else [args.type]
    first = True
    for key in keys:
        label, type_id = TYPES[key]
        items, total_records, total_page, err = fetch_items(
            type_id, args.page_num, args.page_size, sign, args.timeout
        )
        if not first:
            print()
            print("=" * 60)
            print()
        first = False
        if err:
            print(f"# 数字资源·{label}清单（接口返回异常，未取到条目）")
            print()
            print(f"- 接口：{list_url(type_id, args.page_num, args.page_size, sign)}")
            print(f"- 返回片段：{err}")
            print()
            continue
        matched = None
        if args.search:
            items = [it for it in items if args.search in title_of(it)]
            matched = args.search
        print_block(
            label,
            type_id,
            items,
            total_records,
            total_page,
            list_url(type_id, args.page_num, args.page_size, sign),
            matched,
        )
        if not from_page:
            print("（sign 未能从栏目页读取，已使用登记常量；若接口报错，请馆员核对栏目页 var sign）")


if __name__ == "__main__":
    main()
