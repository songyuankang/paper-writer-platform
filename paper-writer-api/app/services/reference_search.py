"""真实参考文献搜索（CrossRef 开放学术库，免费、无需 API Key）。

对应 aiunipaper 的"数据来自中国知网"：本项目无法接入知网（无公开 API），
改用 CrossRef 获取真实学术文献（标题/作者/期刊/年份/DOI/摘要），
并按 GB/T 7714 生成引文，供用户在创作向导第③步搜索选择。
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CROSSREF_API = "https://api.crossref.org/works"
TIMEOUT = 8
USER_AGENT = "paper-writer-api/0.1 (local usage; mailto:local@example.com)"

OPENALEX_API = "https://api.openalex.org/works"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_API = "https://export.arxiv.org/api/query"

DEFAULT_SOURCES = ("crossref", "openalex", "semantic_scholar", "arxiv")

_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# CrossRef 类型 → 文献类型标记（GB/T 7714）
_TYPE_TAG = {
    "journal-article": "J",
    "proceedings-article": "C",
    "dissertation": "D",
    "book": "M",
    "book-chapter": "M",
    "edited-book": "M",
    "posted-content": "EB/OL",
    "report": "R",
    "standard": "S",
}


def _strip_jats(text: str | None) -> str:
    """去掉 CrossRef 摘要里的 JATS XML 标签与转义。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&quot;", '"'))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _format_authors(authors: list[dict]) -> str:
    names: list[str] = []
    for a in authors[:3]:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        if family and given:
            names.append(f"{family} {given}")
        elif family:
            names.append(family)
        elif given:
            names.append(given)
    if len(authors) > 3:
        names.append("等")
    return ",".join(names)


def _citation(item: dict) -> str:
    """把 CrossRef 条目格式化为 GB/T 7714 引文。"""
    title = _strip_jats(" ".join(item.get("title") or [])).strip(" .")
    container = _strip_jats(" ".join(item.get("container-title") or []))
    issued = item.get("issued", {}).get("date-parts", [[None]])
    year = str(issued[0][0]) if issued and issued[0] and issued[0][0] else ""
    volume = str(item.get("volume") or "")
    issue = str(item.get("issue") or "")
    pages = str(item.get("page") or "")
    ctype = item.get("type", "journal-article")
    tag = _TYPE_TAG.get(ctype, "J")
    authors = _format_authors(item.get("author") or [])

    parts = [f"{authors}. {title}[{tag}]."]
    if container:
        parts.append(f"{container},")
    meta: list[str] = []
    if year:
        meta.append(year)
    if volume:
        meta.append(volume)
    if issue:
        meta.append(f"({issue})")
    if meta:
        parts.append(",".join(meta) + ".")
    if pages:
        parts.append(f"{pages}.")
    if item.get("DOI"):
        parts.append(f"DOI:{item['DOI']}.")
    return " ".join(p for p in parts if p)


def _citation_from_values(title: str, authors: str, container: str,
                          year: str, ctype: str, doi: str,
                          extra_ref: str = "") -> str:
    """通用 GB/T 7714 引文生成（OpenAlex / Semantic Scholar / arXiv）。"""
    title = _strip_jats(title).strip(" .")
    container = _strip_jats(container)
    tag = _TYPE_TAG.get(ctype, "J")
    parts = [f"{authors}. {title}[{tag}]."]
    if container:
        parts.append(f"{container},")
    meta: list[str] = []
    if year:
        meta.append(year)
    if meta:
        parts.append(",".join(meta) + ".")
    if extra_ref:
        parts.append(extra_ref + ".")
    if doi:
        parts.append(f"DOI:{doi}.")
    return " ".join(p for p in parts if p)


def _search_crossref(query: str, limit: int = 12) -> list[dict]:
    """按关键词/标题搜索 CrossRef，返回真实文献列表。"""
    params = {
        "query": query,
        "rows": str(min(max(limit, 1), 20)),
        "sort": "relevance",
        "select": "title,author,container-title,issued,volume,issue,page,"
                  "DOI,type,abstract,publisher",
    }
    url = f"{CROSSREF_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out: list[dict] = []
    seen: set[str] = set()
    for item in data.get("message", {}).get("items", []):
        title = _strip_jats(" ".join(item.get("title") or []))
        if not title:
            continue
        if title in seen:
            continue
        seen.add(title)
        issued = item.get("issued", {}).get("date-parts", [[None]])
        year = str(issued[0][0]) if issued and issued[0] and issued[0][0] else ""
        citation = _citation(item)
        if not citation:
            continue
        out.append({
            "title": title,
            "authors": _format_authors(item.get("author") or []),
            "source": _strip_jats(" ".join(item.get("container-title") or [])),
            "year": year,
            "type": item.get("type", "journal-article"),
            "doi": item.get("DOI", ""),
            "abstract": _strip_jats(item.get("abstract") or ""),
            "citation": citation,
            "source_name": "crossref",
        })
    return out


def _openalex_abstract(inverted: dict | None) -> str:
    """OpenAlex 摘要以倒排索引返回，还原为可读文本。"""
    if not isinstance(inverted, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, str(word)))
    positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in positions)


def _search_openalex(query: str, limit: int = 12) -> list[dict]:
    """搜索 OpenAlex（免费开放学术目录）。"""
    params = {
        "search": query,
        "per-page": str(min(max(limit, 1), 20)),
        "select": "id,doi,title,display_name,authorships,publication_year,"
                  "primary_location,abstract_inverted_index,type,ids",
    }
    api_key = os.getenv("OPENALEX_API_KEY", "").strip()
    if api_key:
        params["api_key"] = api_key
    url = f"{OPENALEX_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out: list[dict] = []
    for item in data.get("results", []):
        title = _strip_jats(item.get("title") or item.get("display_name") or "")
        if not title:
            continue
        authors_raw = item.get("authorships") or []
        authors = [a.get("author", {}).get("display_name", "")
                   for a in authors_raw if a.get("author", {}).get("display_name")]
        authors_text = ",".join(authors[:3]) + ("等" if len(authors) > 3 else "")
        location = item.get("primary_location") or {}
        source = (location.get("source") or {}).get("display_name", "")
        doi = (item.get("doi") or "").replace("https://doi.org/", "")
        year = str(item.get("publication_year") or "")
        ctype = item.get("type") or "journal-article"
        citation = _citation_from_values(
            title, authors_text, source, year, ctype, doi)
        if not citation:
            continue
        out.append({
            "title": title,
            "authors": authors_text,
            "source": source,
            "year": year,
            "type": ctype,
            "doi": doi,
            "abstract": _openalex_abstract(
                item.get("abstract_inverted_index")),
            "citation": citation,
            "source_name": "openalex",
        })
    return out


def _search_semantic_scholar(query: str, limit: int = 12) -> list[dict]:
    """搜索 Semantic Scholar（免费 API，低频使用无需 Key）。"""
    params = {
        "query": query,
        "limit": str(min(max(limit, 1), 20)),
        "fields": "title,authors,year,venue,externalIds,abstract,"
                  "publicationTypes",
    }
    url = f"{SEMANTIC_SCHOLAR_API}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": USER_AGENT}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out: list[dict] = []
    for item in data.get("data", []):
        title = _strip_jats(item.get("title") or "")
        if not title:
            continue
        authors_raw = item.get("authors") or []
        authors = [a.get("name", "") for a in authors_raw if a.get("name")]
        authors_text = ",".join(authors[:3]) + ("等" if len(authors) > 3 else "")
        ext = item.get("externalIds") or {}
        doi = (ext.get("DOI") or "").replace("https://doi.org/", "")
        pub_types = item.get("publicationTypes") or []
        ctype = str(pub_types[0]).lower() if pub_types else "journal-article"
        citation = _citation_from_values(
            title, authors_text, item.get("venue") or "",
            str(item.get("year") or ""), ctype, doi)
        if not citation:
            continue
        out.append({
            "title": title,
            "authors": authors_text,
            "source": item.get("venue") or "",
            "year": str(item.get("year") or ""),
            "type": ctype,
            "doi": doi,
            "abstract": _strip_jats(item.get("abstract") or ""),
            "citation": citation,
            "source_name": "semantic_scholar",
        })
    return out


def _search_arxiv(query: str, limit: int = 12) -> list[dict]:
    """搜索 arXiv（免费预印本库，无需 Key）。"""
    params = {
        "search_query": f"all:{query}",
        "start": "0",
        "max_results": str(min(max(limit, 1), 20)),
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        xml_text = resp.read().decode("utf-8")
    root = ET.fromstring(xml_text)

    out: list[dict] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        title = _strip_jats(
            entry.findtext("atom:title", default="", namespaces=_ATOM_NS))
        if not title:
            continue
        authors = [
            a.findtext("atom:name", default="", namespaces=_ATOM_NS)
            for a in entry.findall("atom:author", _ATOM_NS)
        ]
        authors_text = ",".join(authors[:3]) + ("等" if len(authors) > 3 else "")
        published = entry.findtext(
            "atom:published", default="", namespaces=_ATOM_NS)
        year = published[:4] if published else ""
        arxiv_id = (entry.findtext(
            "atom:id", default="", namespaces=_ATOM_NS) or "").strip()
        if arxiv_id.startswith("http://arxiv.org/abs/"):
            arxiv_id = arxiv_id.rsplit("/", 1)[-1]
        elif arxiv_id.startswith("https://arxiv.org/abs/"):
            arxiv_id = arxiv_id.rsplit("/", 1)[-1]
        doi = _strip_jats(entry.findtext(
            "arxiv:doi", default="", namespaces=_ATOM_NS))
        summary = _strip_jats(entry.findtext(
            "atom:summary", default="", namespaces=_ATOM_NS))
        citation = _citation_from_values(
            title, authors_text, "", year, "posted-content", doi,
            extra_ref=f"arXiv:{arxiv_id}" if arxiv_id else "")
        if not citation:
            continue
        out.append({
            "title": title,
            "authors": authors_text,
            "source": "arXiv",
            "year": year,
            "type": "preprint",
            "doi": doi,
            "abstract": summary,
            "citation": citation,
            "source_name": "arxiv",
        })
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    """按标题 / DOI 去重，保留先出现的来源。"""
    seen_titles: set[str] = set()
    seen_dois: set[str] = set()
    out: list[dict] = []
    for item in items:
        title_key = re.sub(r"\s+", "", (item.get("title") or "").lower())
        doi_key = (item.get("doi") or "").lower().strip()
        if title_key and title_key in seen_titles:
            continue
        if doi_key and doi_key in seen_dois:
            continue
        if title_key:
            seen_titles.add(title_key)
        if doi_key:
            seen_dois.add(doi_key)
        out.append(item)
    return out


def search_references(query: str, limit: int = 12,
                      sources: tuple[str, ...] = DEFAULT_SOURCES) -> list[dict]:
    """跨库并发聚合搜索：CrossRef + OpenAlex + Semantic Scholar + arXiv。"""
    per_source = min(max(limit, 1), 5)
    search_fns = {
        "crossref": _search_crossref,
        "openalex": _search_openalex,
        "semantic_scholar": _search_semantic_scholar,
        "arxiv": _search_arxiv,
    }
    results: list[list[dict]] = []
    successful = False
    last_error: Exception | None = None
    with ThreadPoolExecutor(max_workers=max(1, len(sources))) as executor:
        future_map = {
            executor.submit(fn, query, per_source): source
            for source, fn in search_fns.items()
            if source in sources
        }
        for future in as_completed(future_map):
            source = future_map[future]
            try:
                results.append(future.result())
                successful = True
            except Exception:  # noqa: BLE001 - 单源失败不阻塞聚合搜索
                exc = future.exception()
                last_error = exc
                continue
    if not successful and last_error is not None:
        raise last_error
    all_items = [item for rows in results for item in rows]
    return _dedupe(all_items)[:limit]
