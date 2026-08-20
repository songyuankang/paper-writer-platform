"""Literature metadata and evidence layer.

Only public metadata, abstract snippets and explicit user notes enter this store.
Search responses are cached separately and become permanent Literature records only
through an explicit save operation.  This module never downloads or represents a
paper's full text as having been read.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any


from app.config import Settings
from app.services.research_object_service import ResearchObjectService

SOURCES = {"crossref", "openalex", "pubmed", "manual"}
RELATIONS = {"supporting", "contradicting", "contextual", "related"}
EVIDENCE_LOCATIONS = {"abstract", "metadata", "user_note"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_task(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value or ""):
        raise ValueError("任务 ID 无效")
    return value


def _clean(value: Any, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _strip_html(value: Any) -> str:
    return _clean(re.sub(r"<[^>]*>", " ", html.unescape(str(value or ""))), 12000)


def _norm_doi(value: Any) -> str:
    doi = _clean(value, 500).lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    return doi.strip().rstrip(".")


def _year(value: Any) -> int | None:
    try:
        item = int(value)
        return item if 1000 <= item <= 3000 else None
    except (TypeError, ValueError):
        return None


def _authors(value: Any) -> list[str]:
    if not isinstance(value, list): return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = _clean(" ".join(part for part in [item.get("family") or item.get("last_name"), item.get("given") or item.get("first_name")] if part), 240)
        else: name = _clean(item, 240)
        if name: result.append(name)
    return result


def _inverted_abstract(value: Any) -> str:
    if not isinstance(value, dict): return ""
    positions: list[tuple[int, str]] = []
    for word, slots in value.items():
        if isinstance(slots, list):
            positions.extend((int(position), str(word)) for position in slots if isinstance(position, int))
    return _clean(" ".join(word for _, word in sorted(positions)), 12000)


class LiteratureSearchService:
    """Server-side adapters for limited public scholarly metadata search."""
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache_root = settings.db_path.parent / "literature" / "search_cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, payload: dict[str, Any]) -> Path:
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return self.cache_root / f"{digest}.json"

    @staticmethod
    def _crossref(item: dict[str, Any]) -> dict[str, Any]:
        dates = item.get("published-print") or item.get("published-online") or item.get("issued") or {}
        parts = dates.get("date-parts") if isinstance(dates, dict) else []
        year = parts[0][0] if parts and isinstance(parts[0], list) and parts[0] else None
        titles = item.get("title") or []
        return {"source": "crossref", "source_id": str(item.get("member") or ""), "external_id": _norm_doi(item.get("DOI")) or str(item.get("URL") or ""), "title": _clean(titles[0] if titles else "", 1000), "authors": _authors(item.get("author")), "year": _year(year), "journal": _clean((item.get("container-title") or [""])[0], 500), "volume": _clean(item.get("volume"), 120), "issue": _clean(item.get("issue"), 120), "pages": _clean(item.get("page"), 160), "doi": _norm_doi(item.get("DOI")), "url": _clean(item.get("URL"), 1000), "abstract": _strip_html(item.get("abstract")), "publisher": _clean(item.get("publisher"), 500), "keywords": [_clean(value, 160) for value in item.get("subject") or [] if _clean(value, 160)]}

    @staticmethod
    def _openalex(item: dict[str, Any]) -> dict[str, Any]:
        location = item.get("primary_location") or {}; source = location.get("source") or {}
        authors = [((authorship.get("author") or {}).get("display_name") or "") for authorship in item.get("authorships") or []]
        doi = _norm_doi(item.get("doi"))
        return {"source": "openalex", "source_id": _clean(item.get("id"), 500), "external_id": _clean(item.get("id"), 500), "title": _clean(item.get("display_name") or item.get("title"), 1000), "authors": [_clean(value, 240) for value in authors if _clean(value, 240)], "year": _year(item.get("publication_year")), "journal": _clean(source.get("display_name"), 500), "volume": _clean((location.get("landing_page_url") and "") or "", 120), "issue": "", "pages": "", "doi": doi, "url": _clean((location.get("landing_page_url") or item.get("id")), 1000), "abstract": _inverted_abstract(item.get("abstract_inverted_index")), "publisher": _clean(source.get("host_organization_name"), 500), "keywords": [_clean((topic or {}).get("display_name"), 160) for topic in item.get("topics") or [] if _clean((topic or {}).get("display_name"), 160)]}

    @staticmethod
    def _identity(item: dict[str, Any]) -> tuple[str, ...]:
        if item.get("doi"): return ("doi", _norm_doi(item["doi"]))
        if item.get("source") and item.get("external_id"): return ("external", str(item["source"]), str(item["external_id"]))
        author = _clean((item.get("authors") or [""])[0], 180).lower()
        return ("fallback", _clean(item.get("title"), 1000).lower(), str(item.get("year") or ""), author)

    def _dedupe(self, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []; seen: set[tuple[str, ...]] = set()
        for item in values:
            if not item.get("title"): continue
            key = self._identity(item)
            if key in seen: continue
            seen.add(key); output.append(item)
        return output

    @staticmethod
    def _get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        suffix = f"?{urlencode(params, doseq=True)}" if params else ""
        request = Request(url + suffix, headers={"User-Agent": "paper-writer-platform/1.0 (metadata search)"})
        with urlopen(request, timeout=9) as response:
            return json.loads(response.read().decode("utf-8"))

    def _call_crossref(self, query: str, title: str, author: str, start: int | None, end: int | None, doi: str, limit: int) -> list[dict[str, Any]]:
        try:
            if doi:
                response = self._get_json(f"https://api.crossref.org/works/{quote(doi, safe='')}")
                items = [response.get("message") or {}]
            else:
                params: dict[str, Any] = {"rows": limit, "select": "DOI,title,author,published-print,published-online,issued,container-title,volume,issue,page,URL,abstract,publisher,subject,member"}
                if title: params["query.title"] = title
                elif query: params["query.bibliographic"] = query
                if author: params["query.author"] = author
                filters = []
                if start: filters.append(f"from-pub-date:{start}-01-01")
                if end: filters.append(f"until-pub-date:{end}-12-31")
                if filters: params["filter"] = ",".join(filters)
                response = self._get_json("https://api.crossref.org/works", params)
                items = (response.get("message") or {}).get("items") or []
            return [self._crossref(item) for item in items if isinstance(item, dict)]
        except (URLError, TimeoutError, ValueError, OSError):
            return []

    def _call_openalex(self, query: str, title: str, author: str, start: int | None, end: int | None, doi: str, limit: int) -> list[dict[str, Any]]:
        try:
            params: dict[str, Any] = {"per-page": limit}
            if doi: params["filter"] = f"doi:https://doi.org/{doi}"
            else:
                params["search"] = title or query or author
                filters = []
                if start: filters.append(f"from_publication_date:{start}-01-01")
                if end: filters.append(f"to_publication_date:{end}-12-31")
                if filters: params["filter"] = ",".join(filters)
            response = self._get_json("https://api.openalex.org/works", params)
            items = response.get("results") or []
            values = [self._openalex(item) for item in items if isinstance(item, dict)]
            if author:
                lowered = author.lower(); values = [item for item in values if any(lowered in name.lower() for name in item.get("authors") or [])]
            return values
        except (URLError, TimeoutError, ValueError, OSError):
            return []

    def search(self, *, query: str = "", title: str = "", author: str = "", year_from: int | None = None, year_to: int | None = None, doi: str = "", sources: list[str] | None = None, limit: int = 12) -> dict[str, Any]:
        payload = {"query": _clean(query, 500), "title": _clean(title, 500), "author": _clean(author, 240), "year_from": _year(year_from), "year_to": _year(year_to), "doi": _norm_doi(doi), "sources": sorted(set(sources or ["crossref", "openalex"])), "limit": max(1, min(int(limit), 30))}
        if not any([payload["query"], payload["title"], payload["author"], payload["doi"]]): raise ValueError("请至少输入关键词、标题、作者或 DOI")
        if payload["year_from"] and payload["year_to"] and payload["year_from"] > payload["year_to"]: raise ValueError("年份范围无效")
        path = self._cache_path(payload)
        if path.is_file() and time.time() - path.stat().st_mtime < 6 * 3600:
            cached = json.loads(path.read_text(encoding="utf-8")); cached["cached"] = True; return cached
        values: list[dict[str, Any]] = []
        if "crossref" in payload["sources"]: values.extend(self._call_crossref(payload["query"], payload["title"], payload["author"], payload["year_from"], payload["year_to"], payload["doi"], payload["limit"]))
        if "openalex" in payload["sources"]: values.extend(self._call_openalex(payload["query"], payload["title"], payload["author"], payload["year_from"], payload["year_to"], payload["doi"], payload["limit"]))
        result = {"query": payload, "results": self._dedupe(values), "cached": False, "providers": [source for source in payload["sources"] if source in {"crossref", "openalex"}], "warning": "未获得公开元数据结果；可手工录入文献。" if not values else ""}
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


class LiteratureService:
    def __init__(self, settings: Settings):
        self.settings = settings; self.root = settings.db_path.parent / "literature"; self.root.mkdir(parents=True, exist_ok=True)
        self.searcher = LiteratureSearchService(settings)

    def _path(self, literature_id: str) -> Path:
        if not re.fullmatch(r"lit_[A-Za-z0-9]+", literature_id or ""): raise ValueError("Literature ID 无效")
        return self.root / "items" / f"{literature_id}.json"
    def _evidence_dir(self, literature_id: str) -> Path: return self.root / "evidence" / literature_id
    def _link_path(self, task_id: str) -> Path: return self.root / "hypothesis_links" / f"{_safe_task(task_id)}.json"
    def _citation_path(self, task_id: str) -> Path: return self.root / "citations" / f"{_safe_task(task_id)}.json"
    def _draft_path(self, task_id: str) -> Path: return self.settings.output_dir / _safe_task(task_id) / "draft.json"
    def _write(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _all(self, task_id: str | None = None, include_deleted: bool = False) -> list[dict[str, Any]]:
        values = []
        for path in (self.root / "items").glob("lit_*.json") if (self.root / "items").exists() else []:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if task_id and item.get("task_id") != task_id: continue
                if not include_deleted and item.get("status") == "deleted": continue
                values.append(item)
            except json.JSONDecodeError: continue
        return sorted(values, key=lambda item: item.get("updated_at") or "", reverse=True)

    def _match(self, task_id: str, record: dict[str, Any]) -> dict[str, Any] | None:
        doi = _norm_doi(record.get("doi")); external = _clean(record.get("external_id"), 500); source = _clean(record.get("source"), 80)
        title = _clean(record.get("title"), 1000).lower(); year = str(_year(record.get("year")) or ""); first = _clean((record.get("authors") or [""])[0], 180).lower()
        for item in self._all(task_id, include_deleted=True):
            if doi and doi == _norm_doi(item.get("doi")): return item
            if external and source and external == _clean(item.get("external_id"), 500) and source == item.get("source"): return item
            if title and title == _clean(item.get("title"), 1000).lower() and year == str(item.get("year") or "") and first == _clean((item.get("authors") or [""])[0], 180).lower(): return item
        return None

    def _normalize_saved(self, task_id: str, value: dict[str, Any]) -> dict[str, Any]:
        source = str(value.get("source") or "manual").lower()
        if source not in SOURCES: raise ValueError("文献来源无效")
        title = _clean(value.get("title"), 1000)
        if not title: raise ValueError("文献标题不能为空")
        return {"task_id": _safe_task(task_id), "title": title, "authors": _authors(value.get("authors")), "year": _year(value.get("year")), "journal": _clean(value.get("journal"), 500), "volume": _clean(value.get("volume"), 120), "issue": _clean(value.get("issue"), 120), "pages": _clean(value.get("pages"), 160), "doi": _norm_doi(value.get("doi")), "url": _clean(value.get("url"), 1000), "abstract": _clean(value.get("abstract"), 12000), "publisher": _clean(value.get("publisher"), 500), "source": source, "source_id": _clean(value.get("source_id"), 500), "external_id": _clean(value.get("external_id"), 500), "keywords": [_clean(item, 160) for item in value.get("keywords") or [] if _clean(item, 160)], "user_note": _clean(value.get("user_note"), 5000)}

    def save(self, *, task_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        record = self._normalize_saved(task_id, metadata); existing = self._match(task_id, record); timestamp = _now()
        if existing:
            # Trusted source metadata may enrich blanks but never overwrite notes/user changes.
            for key in ["title", "authors", "year", "journal", "volume", "issue", "pages", "doi", "url", "abstract", "publisher", "source", "source_id", "external_id", "keywords"]:
                if record.get(key) and record.get(key) != existing.get(key): existing[key] = record[key]
            if metadata.get("user_note") is not None: existing["user_note"] = record["user_note"]
            existing["metadata_updated"] = True; existing["updated_at"] = timestamp
            if existing.get("status") == "deleted": existing["status"] = "active"
            self._write(self._path(existing["id"]), existing); ResearchObjectService(self.settings).sync(task_id); return existing
        record.update({"id": f"lit_{uuid.uuid4().hex[:16]}", "status": "active", "metadata_updated": False, "created_at": timestamp, "updated_at": timestamp})
        self._write(self._path(record["id"]), record); ResearchObjectService(self.settings).sync(task_id); return record

    def get(self, literature_id: str, include_deleted: bool = True) -> dict[str, Any]:
        path = self._path(literature_id)
        if not path.is_file(): raise ValueError("未找到 Literature")
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("status") == "deleted" and not include_deleted: raise ValueError("文献已删除")
        return item
    def list(self, task_id: str) -> list[dict[str, Any]]: return self._all(_safe_task(task_id))
    def update(self, literature_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        item = self.get(literature_id); protected = {"id", "task_id", "created_at", "status"}
        merged = {**item, **{key: value for key, value in changes.items() if key not in protected}}
        updated = self._normalize_saved(item["task_id"], merged); updated.update({"id": item["id"], "created_at": item["created_at"], "status": item.get("status", "active"), "metadata_updated": item.get("metadata_updated", False), "updated_at": _now()})
        self._write(self._path(literature_id), updated); ResearchObjectService(self.settings).sync(updated["task_id"]); return updated
    def delete(self, literature_id: str) -> dict[str, Any]:
        item = self.get(literature_id); item.update(status="deleted", deleted_at=_now(), updated_at=_now()); self._write(self._path(literature_id), item); ResearchObjectService(self.settings).sync(item["task_id"]); return item

    def add_evidence(self, *, literature_id: str, claim: str, evidence: str, source_location: str, confidence: str = "user_confirmed") -> dict[str, Any]:
        literature = self.get(literature_id, include_deleted=False); source_location = str(source_location)
        if source_location not in EVIDENCE_LOCATIONS: raise ValueError("证据来源位置无效")
        claim, evidence = _clean(claim, 1600), _clean(evidence, 4000)
        if not claim or not evidence: raise ValueError("claim 与 evidence 不能为空")
        source_text = literature.get("abstract") if source_location == "abstract" else literature.get("title") if source_location == "metadata" else literature.get("user_note")
        if source_location != "user_note" and _clean(evidence).lower() not in _clean(source_text, 12000).lower(): raise ValueError("证据必须可在声明的公开摘要或元数据中核验")
        item = {"id": f"le_{uuid.uuid4().hex[:16]}", "literature_id": literature_id, "claim": claim, "evidence": evidence, "source_location": source_location, "confidence": _clean(confidence, 80) or "user_confirmed", "created_at": _now()}
        self._write(self._evidence_dir(literature_id) / f"{item['id']}.json", item); return item
    def evidence(self, literature_id: str) -> list[dict[str, Any]]:
        self.get(literature_id); values=[]
        for path in self._evidence_dir(literature_id).glob("le_*.json") if self._evidence_dir(literature_id).exists() else []:
            try: values.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError: continue
        return sorted(values, key=lambda item: item.get("created_at") or "", reverse=True)

    def _read_links(self, task_id: str) -> list[dict[str, Any]]:
        path=self._link_path(task_id)
        if not path.is_file(): return []
        try: return json.loads(path.read_text(encoding="utf-8")).get("links", [])
        except json.JSONDecodeError: return []
    def _write_links(self, task_id: str, values: list[dict[str, Any]]) -> None: self._write(self._link_path(task_id), {"task_id": task_id, "links": values, "updated_at": _now()})
    def link_hypothesis(self, *, task_id: str, hypothesis_id: str, literature_id: str, relation: str) -> dict[str, Any]:
        relation = str(relation)
        if relation not in RELATIONS: raise ValueError("文献关系无效")
        literature = self.get(literature_id, include_deleted=False)
        if literature.get("task_id") != _safe_task(task_id): raise ValueError("Literature 不属于当前任务")
        # avoid an import cycle while still validating canonical Hypothesis task ownership
        path = self.settings.db_path.parent / "hypotheses" / "items" / f"{hypothesis_id}.json"
        if not path.is_file() or json.loads(path.read_text(encoding="utf-8")).get("task_id") != task_id: raise ValueError("Hypothesis 不属于当前任务")
        values = self._read_links(task_id); current = next((item for item in values if item.get("hypothesis_id") == hypothesis_id and item.get("literature_id") == literature_id), None)
        if current: current.update(relation=relation, updated_at=_now()); self._write_links(task_id, values); return current
        item={"id": f"hl_{uuid.uuid4().hex[:16]}", "task_id": task_id, "hypothesis_id": hypothesis_id, "literature_id": literature_id, "relation": relation, "created_at": _now(), "updated_at": _now()}; values.append(item); self._write_links(task_id, values); return item
    def unlink_hypothesis(self, *, task_id: str, hypothesis_id: str, literature_id: str) -> None:
        values=self._read_links(task_id); filtered=[item for item in values if not (item.get("hypothesis_id") == hypothesis_id and item.get("literature_id") == literature_id)]
        if len(values)==len(filtered): raise ValueError("未找到 Hypothesis-Literature 关联")
        self._write_links(task_id, filtered)
    def hypothesis_literature(self, task_id: str, hypothesis_id: str) -> list[dict[str, Any]]:
        out=[]
        for link in self._read_links(task_id):
            if link.get("hypothesis_id") != hypothesis_id: continue
            try: out.append({"link": link, "literature": self.get(str(link["literature_id"])) , "evidence": self.evidence(str(link["literature_id"]))})
            except ValueError: out.append({"link": link, "literature": None, "evidence": []})
        return out
    def literature_links(self, task_id: str, literature_id: str) -> list[dict[str, Any]]: return [item for item in self._read_links(task_id) if item.get("literature_id") == literature_id]

    def _read_citations(self, task_id: str) -> list[dict[str, Any]]:
        path=self._citation_path(task_id)
        if not path.is_file(): return []
        try: return json.loads(path.read_text(encoding="utf-8")).get("citations", [])
        except json.JSONDecodeError: return []
    def _write_citations(self, task_id: str, values: list[dict[str, Any]]) -> None: self._write(self._citation_path(task_id), {"task_id": task_id, "citations": values, "updated_at": _now()})
    @staticmethod
    def citation_label(literature: dict[str, Any]) -> str:
        authors = literature.get("authors") or []; year = literature.get("year") or "n.d."
        first = _clean(authors[0] if authors else "匿名", 180).split()[-1]
        return f"({first} et al., {year})" if len(authors) >= 3 else f"({first}, {year})" if len(authors) == 1 else f"({first} & {_clean(authors[1], 180).split()[-1]}, {year})" if len(authors) == 2 else f"({first}, {year})"
    def _resolved_citation(self, item: dict[str, Any]) -> dict[str, Any]:
        result=dict(item)
        try: literature=self.get(str(item.get("literature_id")), include_deleted=False)
        except ValueError: literature=None
        if not literature: result.update(status="broken", resolved_label=None, display_label="[引用文献不存在]")
        else: result.update(status="ready", resolved_label=self.citation_label(literature), display_label=self.citation_label(literature), literature_title=literature.get("title"))
        return result
    def create_citation(self, *, task_id: str, literature_id: str, style: str = "author_year", source_block_id: str = "") -> dict[str, Any]:
        literature=self.get(literature_id, include_deleted=False)
        if literature.get("task_id") != _safe_task(task_id): raise ValueError("Literature 不属于当前任务")
        values=self._read_citations(task_id); item={"id": f"ci_{uuid.uuid4().hex[:16]}", "task_id":task_id,"literature_id":literature_id,"style":_clean(style,80) or "author_year","display_label":self.citation_label(literature),"source_block_id":source_block_id,"created_at":_now(),"updated_at":_now()}; values.append(item); self._write_citations(task_id,values); return self._resolved_citation(item)
    def citations(self, task_id: str) -> list[dict[str, Any]]: return [self._resolved_citation(item) for item in self._read_citations(task_id)]
    def insert_citation(self, *, task_id: str, section_id: str, literature_id: str, prefix: str = "", suffix: str = "") -> dict[str, Any]:
        path=self._draft_path(task_id)
        if not path.is_file(): raise ValueError("未找到论文草稿")
        draft=json.loads(path.read_text(encoding="utf-8")); section=next((item for item in draft.get("sections") or [] if item.get("id")==section_id),None)
        if section is None: raise ValueError("未找到插入目标小节")
        block_id=f"p{len(section.get('paragraphs') or [])+1}-{uuid.uuid4().hex[:6]}"; citation=self.create_citation(task_id=task_id,literature_id=literature_id,source_block_id=block_id)
        block={"id":block_id,"type":"literature_citation","text":f"{_clean(prefix,300)}{citation.get('resolved_label')}{_clean(suffix,300)}","content":[{"type":"text","text":_clean(prefix,300)},{"type":"literature_citation","citation_id":citation["id"]},{"type":"text","text":_clean(suffix,300)}]}
        section.setdefault("paragraphs",[]).append(block); path.write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding="utf-8"); return {"citation":citation,"block":block}
    def render_draft_text(self, task_id: str, draft: dict[str, Any]) -> dict[str, str]:
        records={item["id"]:item for item in self.citations(task_id)}; output={}
        for section in draft.get("sections") or []:
            for block in section.get("paragraphs") or []:
                content=block.get("content")
                if not isinstance(content,list): continue
                parts=[]; has=False
                for part in content:
                    if part.get("type")=="text": parts.append(str(part.get("text") or ""))
                    elif part.get("type")=="literature_citation": has=True; parts.append(str((records.get(str(part.get("citation_id"))) or {}).get("resolved_label") or "[引用文献不存在]"))
                if has: output[str(block.get("id"))]="".join(parts)
        return output
    def reference_records(self, task_id: str) -> list[dict[str, Any]]:
        values=[]; seen=set()
        for citation in self.citations(task_id):
            if citation.get("status")!="ready" or citation.get("literature_id") in seen: continue
            seen.add(citation["literature_id"]); values.append(self.get(citation["literature_id"], include_deleted=False))
        return values
