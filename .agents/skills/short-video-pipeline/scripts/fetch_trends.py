#!/usr/bin/env python3
"""
国内外热点与科技资讯统一拉取脚本（纯 Python 标准库，零外部依赖）。

用法（先 source env.sh）：
  python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode all --out runs/<目录>/topic
  python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode tech --out runs/<目录>/topic
  python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode domestic --out runs/<目录>/topic
  python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode global --out runs/<目录>/topic
  python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode search --query "Apple" --out runs/<目录>/topic
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UA = "ShortVideoPipelineBot/1.0 (Mozilla/5.0 Macintosh; Intel Mac OS X 10_15_7)"

# 60s 公共实例按实测可用性与稳定性排序（前两个 10/10 全通，第三个响应最快）
SIXTY_S_HOSTS = [
    "https://api.cczo.cc/60s",
    "https://60s.mizhoubaobei.top",
    "https://60s.okbaike.com",
]

HOT_SEARCH_CRAWLER_URL = "https://solarhell.github.io/hot-search-crawler/latest.json"
NEWSNOW_BASE = "https://newsnow.busiyi.world/api/s?id="

# 实测可用的直连官方科技 / 权威外媒 RSS（1.9s-4.8s，零中间商）
OFFICIAL_RSS_FEEDS: list[tuple[str, str, str]] = [
    ("openai_blog", "OpenAI 官方博客", "https://openai.com/news/rss.xml"),
    ("google_blog", "Google 官方博客", "https://blog.google/rss/"),
    ("deepmind_blog", "Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("apple_newsroom", "Apple Newsroom", "https://www.apple.com/newsroom/rss-feed.rss"),
    ("nvidia_blog", "NVIDIA 官方博客", "https://blogs.nvidia.com/feed/"),
    ("github_blog", "GitHub 官方博客", "https://github.blog/feed/"),
    ("huggingface_blog", "Hugging Face 博客", "https://huggingface.co/blog/feed.xml"),
    ("techcrunch", "TechCrunch", "https://techcrunch.com/feed/"),
    ("theverge", "The Verge", "https://www.theverge.com/rss/index.xml"),
    ("arstechnica", "Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("sspai", "少数派", "https://sspai.com/feed"),
    ("google_news_tech_us", "Google News 全球科技", "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en"),
]

# NewsNow 实测全通的国内外科技/财经/开发者源
NEWSNOW_TECH_GLOBAL: list[tuple[str, str, str]] = [
    ("nn_hackernews", "Hacker News (NewsNow)", "hackernews"),
    ("nn_github", "GitHub Trending", "github-trending-today"),
    ("nn_producthunt", "Product Hunt", "producthunt"),
    ("nn_wallstreetcn", "华尔街见闻快讯", "wallstreetcn-quick"),
    ("nn_cls", "财联社电报", "cls-telegraph"),
    ("nn_ithome", "IT之家 (NewsNow)", "ithome"),
    ("nn_sspai", "少数派 (NewsNow)", "sspai"),
    ("nn_solidot", "Solidot 奇客", "solidot"),
    ("nn_zaobao", "联合早报", "zaobao"),
]

NEWSNOW_DOMESTIC_FALLBACK: list[tuple[str, str, str]] = [
    ("nn_douyin", "抖音热搜 (NewsNow)", "douyin"),
    ("nn_weibo", "微博热搜 (NewsNow)", "weibo"),
    ("nn_zhihu", "知乎热榜 (NewsNow)", "zhihu"),
    ("nn_bilibili", "B站热搜 (NewsNow)", "bilibili-hot-search"),
    ("nn_thepaper", "澎湃新闻", "thepaper"),
]


def http_get(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip, identity"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw


def clean_text(text: str | None, max_len: int = 240) -> str:
    if not text:
        return ""
    s = html.unescape(re.sub(r"<[^>]+>", " ", text))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] + ("…" if len(s) > max_len else "")


def fetch_60s(endpoint: str, label: str, limit: int = 20, timeout: float = 10.0) -> dict[str, Any]:
    errors: list[str] = []
    for host in SIXTY_S_HOSTS:
        url = f"{host}{endpoint}"
        t0 = time.time()
        try:
            raw = http_get(url, timeout=timeout)
            payload = json.loads(raw.decode("utf-8", "replace"))
            if payload.get("code") != 200:
                errors.append(f"{host}: code={payload.get('code')}")
                continue
            data = payload.get("data")
            items: list[dict[str, Any]] = []
            if endpoint == "/v2/ai-news" and isinstance(data, dict):
                news_list = data.get("news") or []
                for it in news_list[:limit]:
                    items.append({
                        "title": clean_text(it.get("title"), 160),
                        "summary": clean_text(it.get("detail"), 240),
                        "hot": it.get("source") or "",
                        "url": it.get("link") or "",
                        "published": it.get("date") or data.get("date") or "",
                    })
            elif isinstance(data, list):
                for it in data[:limit]:
                    if not isinstance(it, dict):
                        continue
                    items.append({
                        "title": clean_text(it.get("title"), 160),
                        "summary": clean_text(it.get("desc") or it.get("detail") or it.get("description"), 240),
                        "hot": it.get("hot_value") or it.get("hot_value_desc") or it.get("score_desc") or it.get("score") or "",
                        "url": it.get("link") or it.get("url") or "",
                        "published": it.get("created") or it.get("event_time") or it.get("active_time") or "",
                    })
            if not items:
                errors.append(f"{host}: empty")
                continue
            return {
                "ok": True,
                "label": label,
                "source_url": url,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "count": len(items),
                "items": items,
            }
        except Exception as exc:
            errors.append(f"{host}: {type(exc).__name__}")
    return {"ok": False, "label": label, "errors": errors, "count": 0, "items": []}


def fetch_newsnow(board_id: str, label: str, limit: int = 20) -> dict[str, Any]:
    url = f"{NEWSNOW_BASE}{urllib.parse.quote(board_id)}"
    t0 = time.time()
    try:
        raw = http_get(url, timeout=10.0)
        payload = json.loads(raw.decode("utf-8", "replace"))
        raw_items = payload.get("items") or []
        items = []
        for it in raw_items[:limit]:
            extra = it.get("extra") if isinstance(it.get("extra"), dict) else {}
            items.append({
                "title": clean_text(it.get("title"), 160),
                "summary": clean_text(extra.get("hover") or extra.get("info") or "", 240),
                "hot": extra.get("info") or "",
                "url": it.get("url") or it.get("mobileUrl") or "",
                "published": str(it.get("pubDate") or ""),
            })
        return {
            "ok": len(items) > 0,
            "label": label,
            "source_url": url,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "count": len(items),
            "items": items,
        }
    except Exception as exc:
        return {"ok": False, "label": label, "source_url": url, "errors": [f"{type(exc).__name__}: {exc}"], "count": 0, "items": []}


def fetch_hn_algolia(limit: int = 15) -> dict[str, Any]:
    url = f"https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}"
    t0 = time.time()
    try:
        raw = http_get(url, timeout=10.0)
        payload = json.loads(raw.decode("utf-8", "replace"))
        items = []
        for h in (payload.get("hits") or [])[:limit]:
            items.append({
                "title": clean_text(h.get("title"), 160),
                "summary": "",
                "hot": f"{h.get('points', 0)} pts / {h.get('num_comments', 0)} comments",
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "published": h.get("created_at") or "",
            })
        return {
            "ok": len(items) > 0,
            "label": "Hacker News (Algolia 官方)",
            "source_url": url,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "count": len(items),
            "items": items,
        }
    except Exception as exc:
        return {"ok": False, "label": "Hacker News (Algolia 官方)", "source_url": url, "errors": [str(exc)], "count": 0, "items": []}


def fetch_rss(url: str, label: str, limit: int = 10) -> dict[str, Any]:
    t0 = time.time()
    try:
        raw = http_get(url, timeout=14.0)
        root = ET.fromstring(raw)
        items: list[dict[str, Any]] = []

        # RSS 2.0
        rss_items = root.findall(".//item")
        if rss_items:
            for el in rss_items[:limit]:
                title = el.findtext("title")
                link = el.findtext("link")
                desc = el.findtext("description") or el.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                pub = el.findtext("pubDate") or el.findtext("{http://purl.org/dc/elements/1.1/}date")
                items.append({
                    "title": clean_text(title, 160),
                    "summary": clean_text(desc, 240),
                    "hot": "",
                    "url": (link or "").strip(),
                    "published": (pub or "").strip(),
                })
        else:
            # Atom
            ns = "{http://www.w3.org/2005/Atom}"
            for el in root.findall(f".//{ns}entry")[:limit]:
                title = el.findtext(f"{ns}title")
                link_el = el.find(f"{ns}link[@rel='alternate']") or el.find(f"{ns}link")
                link = link_el.attrib.get("href", "") if link_el is not None else ""
                desc = el.findtext(f"{ns}summary") or el.findtext(f"{ns}content")
                pub = el.findtext(f"{ns}published") or el.findtext(f"{ns}updated")
                items.append({
                    "title": clean_text(title, 160),
                    "summary": clean_text(desc, 240),
                    "hot": "",
                    "url": link.strip(),
                    "published": (pub or "").strip(),
                })
        return {
            "ok": len(items) > 0,
            "label": label,
            "source_url": url,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "count": len(items),
            "items": items,
        }
    except Exception as exc:
        return {"ok": False, "label": label, "source_url": url, "errors": [f"{type(exc).__name__}: {exc}"], "count": 0, "items": []}


def fetch_crawler_fallback(limit: int = 20) -> dict[str, Any]:
    t0 = time.time()
    try:
        raw = http_get(HOT_SEARCH_CRAWLER_URL, timeout=10.0)
        payload = json.loads(raw.decode("utf-8", "replace"))
        boards = {}
        for b in payload.get("boards") or []:
            bname = b.get("name") or b.get("id") or "unknown"
            boards[bname] = [
                {
                    "title": clean_text(it.get("title"), 160),
                    "summary": "",
                    "hot": it.get("hot") or it.get("hot_value") or "",
                    "url": it.get("url") or it.get("link") or "",
                    "published": "",
                }
                for it in (b.get("items") or [])[:limit]
            ]
        return {
            "ok": len(boards) > 0,
            "label": "hot-search-crawler 兜底",
            "source_url": HOT_SEARCH_CRAWLER_URL,
            "elapsed_ms": int((time.time() - t0) * 1000),
            "boards": boards,
        }
    except Exception as exc:
        return {"ok": False, "label": "hot-search-crawler 兜底", "errors": [str(exc)]}


def canonical_platform(key: str) -> str:
    """将同一底层媒体的多个抓取源归一，避免跨平台统计虚高。"""
    alias = {
        "60s_it_news": "ithome",
        "60s_it_rank": "ithome",
        "nn_ithome": "ithome",
        "nn_sspai": "sspai",
        "rss_sspai": "sspai",
        "nn_hackernews": "hackernews",
        "hn_algolia": "hackernews",
        "60s_douyin": "douyin",
        "nn_douyin": "douyin",
        "60s_weibo": "weibo",
        "nn_weibo": "weibo",
        "60s_zhihu": "zhihu",
        "nn_zhihu": "zhihu",
        "60s_bili": "bilibili",
        "nn_bilibili": "bilibili",
    }
    return alias.get(key, key)


def find_cross_platform(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """简单检测同时出现在 2 个及以上不同底层平台的相近话题（按去标点后短语/关键词重合度）。"""
    entries: list[tuple[str, str, str, str]] = []
    for key, src in sources.items():
        if not src.get("ok"):
            continue
        plat = canonical_platform(key)
        for it in src.get("items") or []:
            t = it.get("title") or ""
            if len(t) >= 4:
                entries.append((key, plat, t, it.get("url") or ""))

    def norm_tokens(s: str) -> set[str]:
        s_clean = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s.lower())
        words = set(w for w in s_clean.split() if len(w) >= 2)
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]+", s_clean))
        bigrams = {cjk[i:i + 2] for i in range(max(0, len(cjk) - 1))}
        return words | bigrams

    tokenized = [(k, p, t, u, norm_tokens(t)) for k, p, t, u in entries]
    clusters: list[dict[str, Any]] = []
    used: set[int] = set()
    for i, (ki, pi, ti, ui, toksi) in enumerate(tokenized):
        if i in used or len(toksi) < 2:
            continue
        group_plats = {pi}
        group_sources = {ki}
        group_titles = [(ki, ti, ui)]
        for j in range(i + 1, len(tokenized)):
            if j in used:
                continue
            kj, pj, tj, uj, toksj = tokenized[j]
            if pj == pi or pj in group_plats or len(toksj) < 2:
                continue
            inter = len(toksi & toksj)
            ratio = inter / min(len(toksi), len(toksj))
            if inter >= 3 and ratio >= 0.45:
                used.add(j)
                group_plats.add(pj)
                group_sources.add(kj)
                group_titles.append((kj, tj, uj))
        if len(group_plats) >= 2:
            used.add(i)
            clusters.append({
                "platforms": sorted(group_plats),
                "sources": sorted(group_sources),
                "platform_count": len(group_plats),
                "representative": ti,
                "matches": [{"source": s, "title": t, "url": u} for s, t, u in group_titles],
            })
    clusters.sort(key=lambda c: c["platform_count"], reverse=True)
    return clusters[:15]


def main() -> int:
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    parser = argparse.ArgumentParser(description="拉取国内外热点、科技/AI热榜及科技巨头一手 RSS")
    parser.add_argument(
        "--mode",
        choices=["all", "domestic", "tech", "global", "rss", "search"],
        default="all",
        help="拉取模式：all(国内外全量) | domestic(国内大众) | tech(国内外科技AI) | global(海外+科技巨头) | rss(仅官方RSS) | search(按词搜新闻)",
    )
    parser.add_argument("--query", default="", help="--mode search 时的搜索词")
    parser.add_argument("--limit", type=int, default=15, help="每个源保留条数（默认 15）")
    parser.add_argument("--out", default="", help="输出目录（如 runs/<目录>/topic），自动写入 hotlist-<mode>.json")
    args = parser.parse_args()

    tasks: dict[str, Any] = {}
    lim = max(1, min(args.limit, 50))

    if args.mode in ("all", "domestic"):
        tasks["60s_douyin"] = lambda: fetch_60s("/v2/douyin", "抖音热榜 (60s)", lim)
        tasks["60s_weibo"] = lambda: fetch_60s("/v2/weibo", "微博热搜 (60s)", lim)
        tasks["60s_bili"] = lambda: fetch_60s("/v2/bili", "B站热搜 (60s)", lim)
        tasks["60s_zhihu"] = lambda: fetch_60s("/v2/zhihu", "知乎热榜 (60s)", lim)
        tasks["60s_toutiao"] = lambda: fetch_60s("/v2/toutiao", "头条热榜 (60s)", lim)
        tasks["60s_baidu"] = lambda: fetch_60s("/v2/baidu/realtime", "百度实时热搜 (60s)", lim)

    if args.mode in ("all", "tech"):
        tasks["60s_it_rank"] = lambda: fetch_60s("/v2/it-news/rank", "IT之家热榜 (60s)", lim)
        tasks["60s_it_news"] = lambda: fetch_60s("/v2/it-news", "IT之家快讯 (60s)", lim)
        tasks["60s_ai_news"] = lambda: fetch_60s("/v2/ai-news", "AI 资讯快报 (60s)", lim, timeout=16.0)
        for key, label, nid in NEWSNOW_TECH_GLOBAL:
            tasks[key] = (lambda n=nid, lb=label: fetch_newsnow(n, lb, lim))

    if args.mode in ("all", "tech", "global", "rss"):
        tasks["hn_algolia"] = lambda: fetch_hn_algolia(lim)
        rss_limit = min(lim, 8)
        for key, label, rurl in OFFICIAL_RSS_FEEDS:
            if args.mode == "tech" and key in ("google_news_tech_us",):
                continue
            tasks[f"rss_{key}"] = (lambda u=rurl, lb=label, rl=rss_limit: fetch_rss(u, lb, rl))

    if args.mode == "global":
        for key, label, nid in NEWSNOW_TECH_GLOBAL[:3]:
            tasks[key] = (lambda n=nid, lb=label: fetch_newsnow(n, lb, lim))
        tasks["nn_zaobao"] = lambda: fetch_newsnow("zaobao", "联合早报", lim)

    if args.mode == "search":
        if not args.query.strip():
            print("错误：--mode search 必须提供 --query", file=sys.stderr)
            return 2
        q = urllib.parse.quote(args.query.strip())
        tasks["google_news_cn"] = lambda: fetch_rss(
            f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            f"Google News 中文 ({args.query.strip()})",
            lim,
        )
        tasks["google_news_en"] = lambda: fetch_rss(
            f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
            f"Google News 英文 ({args.query.strip()})",
            lim,
        )
        tasks["bing_news"] = lambda: fetch_rss(
            f"https://www.bing.com/news/search?q={q}&format=rss",
            f"Bing News ({args.query.strip()})",
            lim,
        )

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        fut_map = {ex.submit(fn): key for key, fn in tasks.items()}
        for fut in as_completed(fut_map):
            key = fut_map[fut]
            results[key] = fut.result()

    # 若国内 60s 主源全部失败，自动降级到 NewsNow 国内源 + hot-search-crawler
    if args.mode in ("all", "domestic"):
        dom_ok = any(results.get(k, {}).get("ok") for k in ("60s_douyin", "60s_weibo", "60s_baidu"))
        if not dom_ok:
            for key, label, nid in NEWSNOW_DOMESTIC_FALLBACK:
                results[key] = fetch_newsnow(nid, label, lim)
            results["fallback_crawler"] = fetch_crawler_fallback(lim)

    cross = find_cross_platform(results)
    fetched_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    bundle = {
        "fetched_at": fetched_at,
        "mode": args.mode,
        "query": args.query or None,
        "summary": {
            "total_sources": len(results),
            "ok_sources": sum(1 for v in results.values() if v.get("ok")),
            "failed_sources": [k for k, v in results.items() if not v.get("ok")],
        },
        "cross_platform_hits": cross,
        "sources": results,
    }

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"hotlist-{args.mode}.json"
        out_file = out_dir / fname
        out_file.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已保存：{out_file}")

    # 输出紧凑摘要给 agent 阅读
    print(f"\n=== 热点汇总（{fetched_at} | mode={args.mode} | 成功 {bundle['summary']['ok_sources']}/{bundle['summary']['total_sources']}）===")
    if bundle["summary"]["failed_sources"]:
        print("失败源:", ", ".join(bundle["summary"]["failed_sources"]))

    if cross:
        print("\n【跨平台同时上榜（高潜选题）】")
        for idx, c in enumerate(cross[:8], 1):
            print(f"  {idx}. [{c['platform_count']}平台: {','.join(c['platforms'])}] {c['representative']}")

    for key in sorted(results.keys()):
        src = results[key]
        if not src.get("ok"):
            continue
        print(f"\n[{key}] {src['label']}（{src['count']}条, {src.get('elapsed_ms', 0)}ms）")
        for idx, it in enumerate((src.get("items") or [])[:5], 1):
            hot = f" ({it['hot']})" if it.get("hot") else ""
            print(f"  {idx}. {it['title']}{hot}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
