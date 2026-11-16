#!/usr/bin/env python3
"""现取北服图书馆「学习支持 / 科研支持 / 资源建设 / 借阅服务」下动态栏目页的最新正文。

页面 ID（2026-11-16 定位，详见 SKILL.md「学研支持动态接口路由」）：

学习支持（learning）
    consult        咨询服务           typeId=5695038
    lecture        讲座培训           typeId=6021124
    lecture_60     60分钟讲座安排     typeId=6021127
    lecture_topics 讲座专题介绍       typeId=6021123
    course         课程教学           typeId=5695041
    orientation    入馆培训           typeId=6021129

科研支持（research）
    subject        学科服务           typeId=5695044
    retrieval      代查代检           typeId=5695046
    core_journals  核心期刊导引       typeId=6021121

资源建设（resource）
    recommend      资源荐购           typeId=5694979
    donation       书刊捐赠           typeId=5694980
    thesis         学位论文提交       typeId=5694981（无 introduction，仅校园网 IP 外链，只照录不访问）

借阅服务（borrow）
    location       馆藏分布           typeId=5695023
    borrow_rule    借阅规则           typeId=5695032
    proxy_borrow   代借服务           typeId=6021232
    cross_campus   通借通还           typeId=5695033
    interlibrary   馆际互借           typeId=5695034（无 introduction，正文在条目列表，1 条 dataId=10789015）
    doc_delivery   文献传递           typeId=5695035（无 introduction，正文在条目列表，5 条）

同空间服务五页共用接口与参数：
    GET https://lib.bift.edu.cn/engine2/general/1690193/more/detail
    engineInstanceId=2412452 & typeId=<见上> & sw= & sign=e1c07d97d45eccffc1e99fff0be5699b

少数栏目正文不在 introduction，而在条目列表里（代查代检），列表接口为：
    GET https://lib.bift.edu.cn/engine2/general/1690193/type/more-clear-datas
    engineInstanceId=2412452 & typeId=<分类> & pageNum=1 & pageSize=100 & sign=... & websiteId=186080 & pageId=331274 & wfwfid=33400
取列表条目的正文再走 detail 接口并带 generalDataId=<条目 dataId>。

响应正文以 \\uXXXX 转义的 JS 对象返回，中文需先解码，正文在 generalDataType.introduction
或 generalData.content。本脚本只打印到标准输出，不写文件、不缓存。

用法：
    python3 scripts/fetch_study_research.py --page consult
    python3 scripts/fetch_study_research.py --page lecture_60
    python3 scripts/fetch_study_research.py --page retrieval --data-id 10802449
    python3 scripts/fetch_study_research.py --group learning      # 仅供馆员核对
    python3 scripts/fetch_study_research.py --page retrieval --list-only
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
COMMON = {
    "appId": "1690193",
    "engineInstanceId": "2412452",
    "sign": "e1c07d97d45eccffc1e99fff0be5699b",
    "websiteId": "186080",
    "pageId": "331274",
    "wfwfid": "33400",
}
PAGES = {
    "consult": {
        "label": "咨询服务", "type_id": "5695038", "group": "learning",
        "column": SITE + "/engine2/general/more?t="
        "BE540DFA47C1CD2902DF3C2B5EECB126B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "lecture": {
        "label": "讲座培训", "type_id": "6021124", "group": "learning",
        "column": SITE + "/engine2/general/more?t="
        "1A3FCEF8FE0C93AF22E9EA3A83EA366AB7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "lecture_60": {
        "label": "60分钟讲座安排", "type_id": "6021127", "group": "learning",
        "column": SITE + "/engine2/general/more?t="
        "1A3FCEF8FE0C93AF22E9EA3A83EA366AB7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "lecture_topics": {
        "label": "讲座专题介绍", "type_id": "6021123", "group": "learning",
        "column": SITE + "/engine2/general/more?t="
        "1A3FCEF8FE0C93AF22E9EA3A83EA366AB7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "course": {
        "label": "课程教学", "type_id": "5695041", "group": "learning",
        "column": SITE + "/engine2/general/more?t="
        "67355CA0454F53143418488CF51A1ED5B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "orientation": {
        "label": "入馆培训", "type_id": "6021129", "group": "learning",
        "column": SITE + "/engine2/general/more?t="
        "1A3FCEF8FE0C93AF274F5C90523EDDA3B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "subject": {
        "label": "学科服务", "type_id": "5695044", "group": "research",
        "column": SITE + "/engine2/general/more?t="
        "67355CA0454F531422E9EA3A83EA366AB7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "retrieval": {
        "label": "代查代检", "type_id": "5695046", "group": "research",
        "column": SITE + "/engine2/general/more?t="
        "67355CA0454F53149D973426BFBA5A1EB7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "core_journals": {
        "label": "核心期刊导引", "type_id": "6021121", "group": "research",
        "column": SITE + "/engine2/general/more?t="
        "1A3FCEF8FE0C93AF3418488CF51A1ED5B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "recommend": {
        "label": "资源荐购", "type_id": "5694979", "group": "resource",
        "column": SITE + "/engine2/general/more?t="
        "CD29A8CC1E497446274F5C90523EDDA3B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "donation": {
        "label": "书刊捐赠", "type_id": "5694980", "group": "resource",
        "column": SITE + "/engine2/general/more?t="
        "39BC4401451576D03954CFAA8E124E88B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "thesis": {
        "label": "学位论文提交", "type_id": "5694981", "group": "resource",
        "column": "http://10.104.25.65/bjfzxy-extend/index.shtml（校园网 IP 直链，仅照录不访问）",
    },
    "location": {
        "label": "馆藏分布", "type_id": "5695023", "group": "borrow",
        "column": SITE + "/engine2/general/more?t="
        "279F51AF032709F2E459C7C2F9A464F4B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "borrow_rule": {
        "label": "借阅规则", "type_id": "5695032", "group": "borrow",
        "column": SITE + "/engine2/general/more?t="
        "BE540DFA47C1CD2970419B45353A2897B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "proxy_borrow": {
        "label": "代借服务", "type_id": "6021232", "group": "borrow",
        "column": SITE + "/engine2/general/more?t="
        "B06F0A74C037FB7870419B45353A2897B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "cross_campus": {
        "label": "通借通还", "type_id": "5695033", "group": "borrow",
        "column": SITE + "/engine2/general/more?t="
        "BE540DFA47C1CD29E459C7C2F9A464F4B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "interlibrary": {
        "label": "馆际互借", "type_id": "5695034", "group": "borrow",
        "column": SITE + "/engine2/general/more?t="
        "BE540DFA47C1CD2922E9EA3A83EA366AB7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
    "doc_delivery": {
        "label": "文献传递", "type_id": "5695035", "group": "borrow",
        "column": SITE + "/engine2/general/more?t="
        "BE540DFA47C1CD29FCDBB912E7EE9D60B7DDA59FFDFE902744EC8E2CF639EB63BE8DADE456461C9250A88391EF6FCAF4",
    },
}
# 文献传递（5695035）5 个条目标题都叫"文献传递"，此映射仅供馆员按平台辨认可取的 dataId，
# 不作为答案依据；答案一律以 --data-id 取回的 content 原文为准。
ITEM_HINTS = {
    "10786094": "BALIS 原文传递（注册开通、收费说明）",
    "10786129": "JULAC 香港地区 8 所高校文献传递",
    "11100904": "CASHL 人文社科外文刊文献传递",
    "10787644": "读秀学术搜索文献传递",
    "10786173": "全国图书馆参考咨询联盟（superlib.net）",
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": SITE + "/engine2/general/more"})
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


def detail_url(params, type_id, data_id=None):
    q = {
        "engineInstanceId": params["engineInstanceId"],
        "typeId": type_id,
        "sw": "",
        "sign": params["sign"],
    }
    if data_id:
        q["generalDataId"] = data_id
    return f"{SITE}/engine2/general/{params['appId']}/more/detail?" + urllib.parse.urlencode(q)


def list_url(params, type_id):
    q = {
        "engineInstanceId": params["engineInstanceId"],
        "typeId": type_id,
        "pageNum": 1,
        "pageSize": 100,
        "sign": params["sign"],
        "websiteId": params["websiteId"],
        "pageId": params["pageId"],
        "wfwfid": params["wfwfid"],
    }
    return f"{SITE}/engine2/general/{params['appId']}/type/more-clear-datas?" + urllib.parse.urlencode(q)


def fetch_list(params, type_id, timeout):
    raw = get(list_url(params, type_id), timeout)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return []
    # 正文型栏目（如 lecture_60）该接口返回 data:null 或无 datas 节点，逐层判断避免 None.get
    if not isinstance(obj, dict):
        return []
    data = obj.get("data")
    if not isinstance(data, dict):
        return []
    datas = data.get("datas")
    if not isinstance(datas, dict):
        return []
    items = datas.get("datas", [])
    return items if isinstance(items, list) else []


def render(key, args):
    page = PAGES[key]
    params = dict(COMMON)
    params["appId"] = args.app_id
    params["engineInstanceId"] = args.engine_instance_id
    params["sign"] = args.sign
    type_id = args.type_id or page["type_id"]

    durl = detail_url(params, type_id, args.data_id)
    decoded = decode(get(durl, args.timeout))
    title = field(decoded, "name") or page["label"]
    intro = field(decoded, "content") if args.data_id else field(decoded, "introduction") or ""
    if intro is None:
        intro = ""
    # 个别栏目（如学位论文提交）无 introduction，只有站外跳转链接，只照录不访问
    outer_url = "" if args.data_id else (field(decoded, "url") or "")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"# {title}（页面 ID={type_id}，接口现取，{now}）")
    print()
    print(f"- 栏目页：{page['column']}")
    print(f"- 实际取回接口：{durl}")
    print(f"- 所属组：{page['group']}")
    print("- 取回方式：GET（服务端返回 Unicode 转义 HTML，本脚本已解码并提取正文）")
    print()
    print("## 正文（照录，未改写）")
    print()
    if intro:
        print(html_to_text(intro))
    elif outer_url:
        print(f"（本页无站内正文，仅登记一个站外跳转地址：{outer_url}）")
        print("按 skill 规则：该地址为校园网 IP，只照录、不访问、不描述其内容。")
    else:
        print("（本页 introduction/content 为空，见下方条目列表）")
    print()
    print(f"## 图片 URL（共 {len(extract_images(intro))} 张，均为 lib.bift.edu.cn 同源）")
    for i, img in enumerate(extract_images(intro), 1):
        print(f"{i}. {img}")
    if not extract_images(intro):
        print("（本次页面无图片）")

    if not args.data_id:
        items = fetch_list(params, type_id, args.timeout)
        print()
        print(f"## 条目列表（共 {len(items)} 条）")
        if not items:
            print("（本栏目无独立条目）")
        for i, it in enumerate(items, 1):
            hint = ITEM_HINTS.get(str(it.get("id")), "")
            hint_str = f"｜{hint}（馆员辨识用，非答案）" if hint else ""
            print(f"{i}. {it.get('typeName') or '（无标题）'}｜dataId={it.get('id')}｜isOuter={it.get('isOuter')}{hint_str}")
            print(f"   取正文命令：python3 scripts/fetch_study_research.py --page {key} --data-id {it.get('id')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--page", choices=list(PAGES), help="取哪个栏目")
    ap.add_argument("--group", choices=["learning", "research", "resource", "borrow"],
                    help="取该组全部页面，仅供馆员核对，不用于单次作答")
    ap.add_argument("--app-id", default=COMMON["appId"])
    ap.add_argument("--engine-instance-id", default=COMMON["engineInstanceId"])
    ap.add_argument("--type-id", help="覆盖分类 ID（页面 ID）；站点改版后由馆员核对填写")
    ap.add_argument("--data-id", help="取指定列表条目的正文（如代查代检 dataId=10802449）")
    ap.add_argument("--sign", default=COMMON["sign"])
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()
    if not args.page and not args.group:
        ap.error("请指定 --page 或 --group")
    if args.group and args.page:
        ap.error("--page 与 --group 不可同时使用")
    keys = ([k for k, v in PAGES.items() if v["group"] == args.group]
            if args.group else [args.page])
    for i, key in enumerate(keys):
        if i:
            print("\n\n" + "=" * 60 + "\n")
        render(key, args)


if __name__ == "__main__":
    main()
