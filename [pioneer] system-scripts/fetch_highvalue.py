#!/usr/bin/env python3
"""news-digest 高价信息源拉取脚本：论文层(arXiv/PubMed) + 媒体层(RSS)。

用法: python3 fetch_highvalue.py [--days N]
默认拉最近 N 天(默认3, 覆盖周末)的论文 + 各 RSS 最新条目，输出纯文本供 agent 分析。
纯标准库，无第三方依赖。输出末尾附总字符数(成本提示)。

2026-08-10 v2:
- arXiv 查询改为简单 AND 形式(复杂 OR 组合实测返回空)
- 日期过滤用 atom:updated，过滤后为空时回退显示最新一条
- RSS 解析兼容 RSS 2.0 与 RDF/RSS 1.0(Nature 格式)
"""
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (news-digest; hermes-agent)"}
DAYS = 3
if "--days" in sys.argv:
    try:
        DAYS = int(sys.argv[sys.argv.index("--days") + 1])
    except (ValueError, IndexError):
        pass

def get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y%m%d")

# ---------- L1 论文层 ----------

# 简单 AND 查询(实测可用)；不写复杂 OR 组合
ARXIV_QUERIES = {
    "医学影像AI": 'cat:cs.CV AND all:"medical image"',
    "BCI脑机接口": 'all:"brain computer interface"',
    "医学3D打印": 'all:"3D printing" AND all:medical',
    "生信": 'cat:q-bio.GN AND all:genomics',
}

def fetch_arxiv() -> None:
    print("===== L1 论文层: arXiv =====")
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    cut = cutoff()
    for label, query in ARXIV_QUERIES.items():
        url = ("https://export.arxiv.org/api/query?"
               + urllib.parse.urlencode({
                   "search_query": query,
                   "sortBy": "submittedDate",
                   "sortOrder": "descending",
                   "max_results": 8,
               }))
        try:
            root = ET.fromstring(get(url))
            entries = root.findall("atom:entry", ns)
            print(f"\n--- {label} (arXiv, 最近 {DAYS} 天) ---")
            shown = 0
            newest = None
            for e in entries:
                pub = e.findtext("atom:updated", default="", namespaces=ns)[:10]
                pub_compact = pub.replace("-", "")
                if newest is None:
                    newest = (pub, " ".join(e.findtext("atom:title", default="", namespaces=ns).split()),
                              e.findtext("atom:id", default="", namespaces=ns))
                if pub_compact < cut:
                    continue
                title = " ".join(e.findtext("atom:title", default="", namespaces=ns).split())
                link = e.findtext("atom:id", default="", namespaces=ns)
                print(f"- [{pub}] {title}\n  {link}")
                shown += 1
            if shown == 0:
                if newest:
                    print(f"  (最近 {DAYS} 天无新增; 最新一条 {newest[0]}: {newest[1]}\n  {newest[2]})")
                else:
                    print("  (无结果)")
        except Exception as ex:
            print(f"  [失败] {label}: {ex}")
        time.sleep(1)  # arXiv 限流礼貌

def fetch_pubmed() -> None:
    print("\n===== L1 论文层: PubMed =====")
    terms = {
        "BCI": '(brain-computer interface[Title/Abstract]) OR (brain computer interface[Title/Abstract])',
        "医学影像AI": '(medical image[Title/Abstract] AND deep learning[Title/Abstract])',
    }
    for label, term in terms.items():
        esearch = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
                   + urllib.parse.urlencode({
                       "db": "pubmed", "term": term, "retmax": 5,
                       "sort": "date", "retmode": "json",
                   }))
        try:
            ids = json.loads(get(esearch).decode("utf-8"))["esearchresult"].get("idlist", [])
        except Exception as ex:
            print(f"  [失败] {label} esearch: {ex}")
            continue
        if not ids:
            print(f"\n--- {label} (PubMed) ---\n  (无结果)")
            continue
        esummary = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
                    + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "json"}))
        try:
            summ = json.loads(get(esummary).decode("utf-8"))["result"]
        except Exception as ex:
            print(f"  [失败] {label} esummary: {ex}")
            continue
        print(f"\n--- {label} (PubMed) ---")
        for pid in ids:
            item = summ.get(pid, {})
            title = " ".join(item.get("title", "").split())
            date = (item.get("pubdate", "") or "")[:10]
            print(f"- [{date}] {title}\n  https://pubmed.ncbi.nlm.nih.gov/{pid}/")
        time.sleep(1)  # NCBI 限流礼貌

# ---------- L3 媒体层 (RSS, 兼容 2.0 + RDF/1.0) ----------

RSS_FEEDS = {
    "Nature": "https://www.nature.com/nature.rss",
    "MIT Tech Review": "https://www.technologyreview.com/feed/",
    "STAT News": "https://www.statnews.com/feed/",
}

def parse_rss_items(root, limit: int = 6):
    items = []
    for it in root.iter():
        if not (it.tag == "item" or it.tag.endswith("}item")):
            continue
        title = pub = link = ""
        for child in it:
            tag = child.tag.split("}")[-1]
            if tag == "title" and not title:
                title = " ".join((child.text or "").split())
            elif tag in ("pubDate", "date") and not pub:
                pub = (child.text or "")[:16]
            elif tag == "link" and not link:
                link = (child.text or "").strip()
        about = it.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") or it.get("about")
        if not link and about:
            link = about
        items.append((title, pub, link))
    return items[:limit]

def fetch_rss() -> None:
    print("\n===== L3 媒体层: RSS =====")
    for label, url in RSS_FEEDS.items():
        try:
            root = ET.fromstring(get(url))
            items = parse_rss_items(root)
            print(f"\n--- {label} ---")
            for title, pub, link in items:
                print(f"- [{pub}] {title}\n  {link}")
            if not items:
                print("  (无条目或解析失败)")
        except Exception as ex:
            print(f"  [失败] {label}: {ex}")

# ---------- main ----------

def main() -> None:
    print(f"# news-digest 高价信息拉取 @ {datetime.now().strftime('%Y-%m-%d %H:%M')} (最近 {DAYS} 天)")

    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        fetch_arxiv()
        fetch_pubmed()
        fetch_rss()
    finally:
        sys.stdout = old_stdout
    out = buf.getvalue()
    print(out)
    print(f"# 拉取完成 (共 {len(out)} 字符, 纯文本供 agent 分类打分)")

if __name__ == "__main__":
    main()
