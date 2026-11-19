#!/usr/bin/env python3
"""经搜狗微信搜索（weixin.sogou.com）检索北服图书馆官方公众号近期文章。

账号锁定（硬约束）：只采信公众号名称精确等于「北京服装学院图书馆」、
微信 ID 登记为 BIFT_LIB 这一个账号；其他账号（近似号、转载号、营销号）
一律排除。搜狗结果不暴露微信 ID，故脚本以账号名精确匹配为过滤主判据，
ID 作为登记常量随结果输出供 SKILL.md 核验，不据近似名放行。

LookBook 别名归一化（硬约束）：检索词中的 lookbook / look book（大小写不限）
统一改写为馆方标准写法「Look·Book」再检索（搜狗按 LookBook 会漏检），
输出会写明「别名归一化」；已是标准写法时幂等不变。

实测结构（2026-11-19）：
    搜索接口：GET https://weixin.sogou.com/weixin?type=2&query=<词>&ie=utf8
    结果条目：<li id="sogou_vr_11002601_box_N" ...>...</li>
      标题   <h3> 内文本（含 <em><!--red_beg-->..<!--red_end--></em> 高亮）
      摘要   <p class="txt-info" ...>
      账号名 <span class="all-time-y2">公众号名</span>
      时间   <script>document.write(timeConvert('<unix秒>'))</script>
      跳转   <a href="/link?url=...&type=2&query=...&token=...">
    结果按相关性排序，非时间序，本脚本自行按时间戳倒序并用 --days/--top 过滤。

退出码（SystemExit 语义，交由 SKILL.md 兜底）：
    0 成功且有命中（指定账号）；含「原文取不到、降级为摘要」的情形（不单独占码）
    1 检索成功但指定账号 0 命中（含 --days 窗口过滤后无命中）
    2 网络错误/验证码/反爬阻断
    注：非指定账号不构成独立失败码，过滤后无命中即返回 1；原文取不到只在正文处标注
    「非原文全文」并向 stderr 提示，退出码仍为 0。

用法：
    python3 scripts/fetch_wechat_search.py --search 开馆安排
    python3 scripts/fetch_wechat_search.py --search 讲座 --days 90 --top 20
    python3 scripts/fetch_wechat_search.py --search 开馆 --fetch-original
    python3 scripts/fetch_wechat_search.py --search 开馆 --json
"""

import argparse
import datetime
import html as html_mod
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

SOGOU = "https://weixin.sogou.com"
ACCOUNT_NAME = "北京服装学院图书馆"   # 唯一授权账号名（精确匹配）
ACCOUNT_ID = "BIFT_LIB"              # 登记微信 ID（搜狗不暴露，供核验标注）
# LookBook 别名归一化：读者口语写法 → 馆方公众号标准写法「Look·Book」。
# 搜狗以「LookBook」检索会漏检，按标准写法才能召回相关文章。
LOOKBOOK_PATTERN = re.compile(r"look\s*book", re.IGNORECASE)
LOOKBOOK_CANONICAL = "Look·Book"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def get(url, timeout):
    # 搜狗跳转链接的 query 参数常含未编码空格（如「…图书馆 LookBook」），
    # urllib 会抛 http.client.InvalidURL（ValueError 子类）；先规范化空白再请求。
    url = re.sub(r"\s+", "%20", url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": SOGOU})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SystemExit(f"[码2] 取页失败：{exc}\n接口：{url}")


def clean(html_fragment):
    """去高亮标记与标签，还原实体，压空白。"""
    s = re.sub(r"<!--.*?-->", "", html_fragment, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_query(query):
    """LookBook 别名归一化：lookbook / look book（大小写不限）→ Look·Book。

    只替换检索词中的该片段，账号名与其余事项词原样保留；已是标准写法时幂等不变。
    返回 (归一化后的检索词, 是否发生了替换)。
    """
    normalized = LOOKBOOK_PATTERN.sub(LOOKBOOK_CANONICAL, query)
    return normalized, normalized != query


def search_url(query):
    return SOGOU + "/weixin?" + urllib.parse.urlencode(
        {"type": 2, "query": query, "ie": "utf8"}
    )


def blocked(page):
    """验证码 / 反爬拦截页判定。"""
    return bool(re.search(
        r"请输入验证码|验证码|seccode|antispider|访问过于频繁|滑动验证|此账号已被限制",
        page,
    ))


def parse_items(page):
    """从搜索结果页解析条目；返回 (全部条目, 被账号过滤掉的条数)。"""
    items = []
    lis = re.findall(r'<li id="sogou_vr_11002601_box_\d+".*?</li>', page, re.S)
    dropped = 0
    for li in lis:
        m_h3 = re.search(r"<h3>.*?</h3>", li, re.S)
        m_sum = re.search(r'<p class="txt-info"[^>]*>(.*?)</p>', li, re.S)
        m_acct = re.search(r'class="all-time-y2"[^>]*>(.*?)</span>', li, re.S)
        m_ts = re.search(r"timeConvert\('(\d+)'\)", li)
        m_href = re.search(r'<h3>\s*<a[^>]+href="([^"]+)"', li, re.S)
        if not (m_h3 and m_acct):
            continue
        acct = clean(m_acct.group(1))
        # 账号锁定：名称精确匹配，绝不放行近似名
        if acct != ACCOUNT_NAME:
            dropped += 1
            continue
        title = clean(m_h3.group(0))
        summary = clean(m_sum.group(1)) if m_sum else ""
        ts = int(m_ts.group(1)) if m_ts else None
        pub = (datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
               if ts else "")
        link = (html_mod.unescape(m_href.group(1)) if m_href else "")
        if link.startswith("/"):
            link = SOGOU + link
        items.append({
            "account": acct,
            "account_id_registered": ACCOUNT_ID,
            "account_verified": True,   # 名称精确匹配即通过主判据；ID 由 SKILL.md 登记核验
            "title": title,
            "summary": summary,
            "publish_date": pub,
            "timestamp": ts,
            "sogou_link": link,
            "original_link": "",
            "content": "",
        })
    # 按时间戳倒序（搜狗默认按相关性，非时间序）
    items.sort(key=lambda x: x["timestamp"] or 0, reverse=True)
    return items, dropped


def fetch_original(link, timeout):
    """跟随搜狗跳转尝试取 mp.weixin.qq.com 原文正文；失败返回空串。"""
    try:
        page = get(link, timeout)
    except SystemExit:
        return ""
    # 跳转页常含 JS meta refresh，提取真实原文地址
    m = re.search(r'(?:url=|URL=)(https?://mp\.weixin\.qq\.com/[^"\'\s>]+)', page)
    final = html_mod.unescape(m.group(1)) if m else ""
    body = page
    if final:
        try:
            body = get(final, timeout)
        except SystemExit:
            return ""
    # 微信正文在 id="js_content" 容器内
    m = re.search(r'id="js_content"[^>]*>(.*?)</div>\s*</div>', body, re.S)
    if not m:
        m = re.search(r'id="js_content"[^>]*>(.*)', body, re.S)
    if not m:
        return ""
    return clean(m.group(1))


def render_text(items, dropped, args):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"# 搜狗微信搜索·指定账号「{ACCOUNT_NAME}」(ID {ACCOUNT_ID}) 账号命中 {len(items)} 条（{now}）")
    print()
    print(f"- 检索词：{args.search}")
    if getattr(args, "query_alias_note", ""):
        print(f"- 别名归一化：{args.query_alias_note}")
    print(f"- 账号过滤：名称精确匹配「{ACCOUNT_NAME}」，丢弃其他账号 {dropped} 条")
    print(f"- 搜狗检索接口：{search_url(args.search)}")
    print(f"- 注1：搜狗结果不暴露微信 ID，ID 为登记常量；账号名精确匹配为主判据")
    print(f"- 注2：账号命中≠内容命中。搜狗以账号名为主关键词，返回的多为该账号其他文章，"
          f"事项词未必生效；照录前须逐条核对标题／摘要是否与所问事项相关，无关者不得照录")
    print()
    for i, it in enumerate(items, 1):
        print(f"## {i}. {it['title']}")
        print()
        print(f"- 公众号：{it['account']}（ID {it['account_id_registered']}）")
        print(f"- 发布时间：{it['publish_date']}")
        print(f"- 搜狗跳转：{it['sogou_link']}")
        if it["original_link"]:
            print(f"- 原文链接：{it['original_link']}")
        print(f"- 摘要：{it['summary'] or '（无摘要）'}")
        if args.fetch_original:
            if it["content"]:
                print(f"- 原文正文（照录，未改写）：\n  {it['content']}")
            else:
                print("- 原文正文：未能取到（降级为摘要，非原文全文）")
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--search", required=True, help="搜狗微信文章搜索关键词")
    ap.add_argument("--days", type=int, default=90,
                    help="近期窗口：发布时间距今 ≤ N 天；0 表示不按时间过滤（默认 90）")
    ap.add_argument("--top", type=int, default=20,
                    help="按时间倒序最多返回 N 条（默认 20）")
    ap.add_argument("--fetch-original", action="store_true",
                    help="尝试跟随跳转取 mp.weixin.qq.com 原文正文（可能失败）")
    ap.add_argument("--json", action="store_true", help="结构化 JSON 输出")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    # LookBook 别名归一化：读者说 lookbook / look book（大小写不限）时，
    # 统一按馆方标准写法「Look·Book」检索，避免漏检。
    query, alias_changed = normalize_query(args.search)
    args.query_alias_note = (
        f"「{args.search}」→「{query}」（LookBook 标准写法，避免漏检）"
        if alias_changed else ""
    )
    args.search = query

    page = get(search_url(args.search), args.timeout)
    if blocked(page):
        raise SystemExit("[码2] 搜狗返回验证码/反爬拦截页，停止并回退官网；不绕过、不破解")
    items, dropped = parse_items(page)

    # --days 近期窗口过滤（发布时间距今 ≤ N 天）
    if args.days > 0:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=args.days)
        cut_ts = int(cutoff.timestamp())
        items = [x for x in items if (x["timestamp"] or 0) >= cut_ts]
    items = items[: args.top]

    if not items:
        hint = (f"；当前 --days={args.days} 可能过严（公众号更新可能早于该窗口），"
                f"可放宽天数重试后再决定回退" if args.days > 0 else "")
        raise SystemExit(
            f"[码1] 检索成功，但「{ACCOUNT_NAME}」(ID {ACCOUNT_ID}) 无命中"
            f"（其他账号丢弃 {dropped} 条）{hint}；回退官网最新资讯路由"
        )

    if args.fetch_original:
        for it in items:
            body = fetch_original(it["sogou_link"], args.timeout)
            if body:
                it["content"] = body
        # 全部命中都取不到原文时，码 3：降级为摘要（仍打印摘要供照录）
        if not any(x["content"] for x in items) and not args.json:
            print("[提示] 原文均未取到，以下仅为搜狗结果摘要，非公众号原文全文。", file=sys.stderr)

    if args.json:
        print(json.dumps({
            "account_name": ACCOUNT_NAME,
            "account_id_registered": ACCOUNT_ID,
            "query": args.search,
            "query_alias_note": args.query_alias_note,
            "dropped_other_accounts": dropped,
            "items": items,
        }, ensure_ascii=False, indent=2))
    else:
        render_text(items, dropped, args)


if __name__ == "__main__":
    main()
