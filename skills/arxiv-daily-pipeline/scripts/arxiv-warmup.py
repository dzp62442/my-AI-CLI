#!/usr/bin/env python3
"""arxiv 批次 URL 预热脚本 — 构建主程序将要请求的全部批次 API URL 清单。

背景（2026-09-25）：arXiv 侧对 Python 客户端的「缓存未命中」请求间歇性 406；
curl 可正常通过并填充 CDN 缓存，之后 Python 走「缓存命中」路径即可稳定通过。
本脚本复刻 zotero_arxiv_daily 的 RSS 解析与分批逻辑（只读，不改动项目），
输出 URL 清单供 launch 脚本用 curl 预热。

用法: python arxiv-warmup.py [输出文件路径]
退出码: 0=成功; 1=失败（RSS 错误/无 ID，调用方应跳过预热继续原流程）
"""
import sys

import feedparser

from urllib.parse import urlencode

OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/dzp62442/.hermes/cache/arxiv-warm_urls.txt"

# 与项目 config/custom.yaml 保持一致（source.arxiv.category + include_cross_list: false）
QUERY = "cs.AI+cs.CV+cs.RO"
ALLOWED_ANNOUNCE_TYPES = {"new"}

# 与 arxiv-daily-launch.sh 的预检保持一致
PRECHECK_ID = "1706.03762v7"


def build_url(ids: list[str]) -> str:
    """与 arxiv 库 Client._format_url 逐字节一致的 URL 构造（参数顺序敏感）。"""
    args = {
        "search_query": "",
        "id_list": ",".join(ids),
        "sortBy": "relevance",
        "sortOrder": "descending",
        "start": "0",
        "max_results": "100",
    }
    return "https://export.arxiv.org/api/query?" + urlencode(args)


def main() -> int:
    feed = feedparser.parse(f"https://rss.arxiv.org/atom/{QUERY}")
    title = getattr(feed.feed, "title", "")
    if "Feed error for query" in str(title):
        print(f"[warmup-build] RSS ERROR: {title}")
        return 1

    ids = [
        e.id.removeprefix("oai:arXiv.org:")
        for e in feed.entries
        if e.get("arxiv_announce_type", "new") in ALLOWED_ANNOUNCE_TYPES
    ]
    print(f"[warmup-build] RSS OK: {title} | new ids: {len(ids)}")
    if not ids:
        print("[warmup-build] NO IDS — abort")
        return 1

    urls = [build_url(ids[i : i + 20]) for i in range(0, len(ids), 20)]
    urls.append(build_url([PRECHECK_ID]))  # 预检 URL 一并预热，让预检走缓存命中

    with open(OUT, "w") as f:
        f.write("\n".join(urls) + "\n")
    print(f"[warmup-build] batch urls: {len(urls) - 1} + 1 precheck = {len(urls)} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
