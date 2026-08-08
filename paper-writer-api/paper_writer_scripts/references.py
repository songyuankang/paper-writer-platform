#!/usr/bin/env python3
"""Reference management for paper-writer: import, format, convert and check.

Subcommands:
  import   Import references (.bib / .enl / .txt Word list) into references.json
  format   Render references.json as a formatted list (GB/T 7714 / APA / MLA / Chicago)
  check    Check a paper_spec.json against references.json -> ReferenceCheck.md

Usage:
  python references.py import --input refs.bib --out references.json \\
      --style gb7714 --citation numeric
  python references.py format --references references.json --style apa \\
      --citation author_year --out formatted_refs.txt
  python references.py check --spec paper_spec.json --references references.json \\
      --style gb7714 --citation numeric --out ReferenceCheck.md

references.json entry schema (also produced for auto-generated references):
{
  "key": "zhang2025",
  "type": "journal | book | thesis | conference | web | other",
  "title": "...",
  "author": "张三",
  "authors": ["张三"],
  "year": "2025",
  "source": "期刊/出版社/会议名称",
  "volume": "", "issue": "", "pages": "",
  "publisher": "", "city": "", "doi": "", "url": "",
  "citation": "[1]",
  "verified": false,
  "raw": "", "note": ""
}

verified=false marks 示例文献 / 启发式解析结果 that need manual confirmation;
ReferenceCheck.md lists them under 疑似不存在文献提示.
"""

import argparse
import json
import re
import sys
from pathlib import Path

STYLES = ("gb7714", "apa", "mla", "chicago")
CITATIONS = ("numeric", "author_year")
TYPE_LABEL = {
    "journal": "J", "book": "M", "thesis": "D", "conference": "C",
    "web": "EB/OL", "other": "Z",
}
EMPTY_ENTRY = {
    "key": "", "type": "other", "title": "", "author": "", "authors": [],
    "year": "", "source": "", "volume": "", "issue": "", "pages": "",
    "publisher": "", "city": "", "doi": "", "url": "",
    "citation": "", "verified": False, "raw": "", "note": "",
}


def norm_title(text):
    return re.sub(r"[\s\u3000\W]+", "", text or "").casefold()


def is_ascii(text):
    return all(ord(c) < 128 for c in text or "")


def clean(value):
    if value is None:
        return ""
    value = re.sub(r"[\s\u3000]+", " ", str(value)).strip()
    return re.sub(r"[\{\}]", "", value)


def make_entry(**kw):
    e = dict(EMPTY_ENTRY)
    e.update({k: v for k, v in kw.items() if v is not None})
    e["authors"] = e.get("authors") or []
    e["author"] = e.get("author") or "；".join(e["authors"])
    return e


# ------------------------------------------------------------------ importers

def parse_bib(path):
    entries = []
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    text = re.sub(r"(?im)^@online\b", "@misc", text)
    try:
        import bibtexparser
        lib = bibtexparser.loads(text)
        raw_list = lib.entries
    except Exception:
        raw_list = _fallback_bib(text)
    type_map = {
        "article": "journal", "book": "book", "inbook": "book",
        "inproceedings": "conference", "conference": "conference",
        "phdthesis": "thesis", "mastersthesis": "thesis",
        "online": "web", "electronic": "web", "misc": "other",
    }
    for i, raw in enumerate(raw_list):
        btype = (raw.get("ENTRYTYPE") or "misc").lower()
        authors = [clean(a) for a in re.split(r"\s+and\s+", raw.get("author", ""))
                   if clean(a)]
        year = clean(raw.get("year") or (raw.get("date") or "")[:4])
        if btype in ("phdthesis", "mastersthesis"):
            source = clean(raw.get("school"))
        elif btype in ("inproceedings", "conference"):
            source = clean(raw.get("booktitle"))
        elif btype == "article":
            source = clean(raw.get("journal"))
        else:
            source = clean(raw.get("publisher"))
        pages = clean(raw.get("pages")).replace("--", "-")
        if btype == "misc" and (raw.get("url") or raw.get("howpublished")):
            etype = "web"
        else:
            etype = type_map.get(btype, "other")
        entries.append(make_entry(
            key=clean(raw.get("ID") or f"ref{i+1}"),
            type=etype,
            title=clean(raw.get("title")),
            authors=authors,
            year=year,
            source=source,
            volume=clean(raw.get("volume")),
            issue=clean(raw.get("number")),
            pages=pages,
            publisher=clean(raw.get("publisher")),
            city=clean(raw.get("address")),
            doi=clean(raw.get("doi")),
            url=clean(raw.get("url")),
            verified=True,
            note=f"导入自 BibTeX（{btype}）",
            raw=raw.get("raw", ""),
        ))
    return entries


def _fallback_bib(text):
    """Minimal BibTeX parser used when bibtexparser is unavailable."""
    out = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        btype, key = m.group(1).lower(), m.group(2)
        body = _balanced_braces(text, m.end())
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|(\"[^\"]*\"))", body):
            name, braced, quoted = fm.group(1).lower(), fm.group(2), fm.group(3)
            fields[name] = (braced or quoted or "").strip().strip('"')
        fields["ENTRYTYPE"] = btype
        fields["ID"] = key
        out.append(fields)
    return out


def _balanced_braces(text, start):
    """Return the substring from start up to the matching closing brace."""
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return text[start:i]
    return text[start:]


def parse_enl(path):
    import xml.etree.ElementTree as ET
    tree = ET.parse(path)
    entries = []
    type_map = {
        "journal article": "journal", "book": "book", "thesis": "thesis",
        "conference paper": "conference", "web page": "web",
        "report": "other", "electronic article": "journal",
    }
    for rec in tree.iter("record"):
        def first(tag):
            el = rec.find(f".//{tag}")
            return clean(el.text) if el is not None else ""
        ref_el = rec.find("ref-type")
        if ref_el is not None:
            ref_type = ref_el.get("name", "")
        else:
            ref_type = ""
        authors = [clean(a.text) for a in rec.findall(".//authors/author")
                   if clean(a.text)]
        if not authors:
            authors = [clean(a.text) for a in rec.findall(".//author")
                       if clean(a.text)]
        source = first("secondary-title") or first("full-title") or first("publisher")
        entries.append(make_entry(
            key=first("rec-number") or f"enl{len(entries)+1}",
            type=type_map.get((ref_type or "").lower(), "other"),
            title=first("title"),
            authors=authors,
            year=first("year"),
            source=source,
            volume=first("volume"),
            issue=first("number"),
            pages=first("pages"),
            publisher=first("publisher"),
            city=first("pub-location") or first("city"),
            doi=first("electronic-resource-num"),
            url=first("url"),
            verified=True,
            note="导入自 EndNote (.enl)",
        ))
    return entries


def parse_word_list(text):
    entries = []
    type_map = {"J": "journal", "M": "book", "D": "thesis", "C": "conference",
                "EB/OL": "web", "R": "other", "N": "other", "S": "other"}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        raw = re.sub(r"^\s*(?:\[\d+\]|\d+[\.、\)])\s*", "", line)
        tm = re.search(r"\[(J|M|D|C|EB/OL|R|N|S|P)\]", raw)
        etype = type_map.get(tm.group(1), "other") if tm else "other"
        year_m = re.search(r"(19\d{2}|20\d{2})", raw)
        volume = issue = pages = source = ""
        # Best-effort GB/T 7714 decomposition: "作者. 题名[X]. 来源, 年, 卷(期): 页码."
        title = raw
        author = ""
        if tm:
            before, after = raw[:tm.start()], raw[tm.end():]
            segs = [s.strip() for s in before.split(". ")]
            if segs and re.match(r"^[\u4e00-\u9fffA-Za-z\s·,，、.-]{1,60}$", segs[0]):
                author = segs[0]
                title = ".".join(segs[1:]) if len(segs) > 1 else segs[0]
            tail = after.strip(" ./，,，")
            ypos = re.search(r"(19\d{2}|20\d{2})", tail)
            if ypos:
                source = tail[:ypos.start()].strip(" .，,,")
                rest = tail[ypos.end():]
                vip = re.search(r",?\s*(\d+)\s*\((\d+)\)\s*:\s*([\d-]+)", rest)
                if vip:
                    volume, issue, pages = vip.group(1), vip.group(2), vip.group(3)
                else:
                    pages_m = re.search(r":\s*([\d-]+)", rest)
                    if pages_m:
                        pages = pages_m.group(1)
            else:
                source = tail
        entries.append(make_entry(
            key=f"word{len(entries)+1}",
            type=etype,
            title=clean(title),
            authors=[clean(author)] if author else [],
            year=year_m.group(1) if year_m else "",
            source=clean(source),
            volume=volume,
            issue=issue,
            pages=pages,
            verified=False,
            note="Word 参考文献列表导入，字段为启发式解析，请人工核对",
            raw=line,
        ))
    return entries


def import_refs(inputs):
    merged = []
    for path in inputs:
        p = Path(path)
        ext = p.suffix.lower()
        if ext == ".bib":
            merged += parse_bib(p)
        elif ext == ".enl":
            merged += parse_enl(p)
        else:
            merged += parse_word_list(p.read_text(encoding="utf-8-sig", errors="replace"))
    return dedupe(merged)


def dedupe(entries):
    seen, out = set(), []
    for e in entries:
        key = (norm_title(e["title"]), e["year"], (e["authors"][0] if e["authors"] else ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


# ------------------------------------------------------------------ formatting

def split_name(name):
    name = clean(name)
    if "," in name:
        surname, given = [s.strip() for s in name.split(",", 1)]
        return surname, given
    parts = name.split()
    if len(parts) <= 1:
        return name, ""
    return parts[-1], " ".join(parts[:-1])


def initials(given):
    return "".join(f"{w[0]}." for w in re.findall(r"[A-Za-z\u4e00-\u9fff]+", given))


def fmt_author_gb7714(name, et_al):
    return name


def fmt_author_apa(name):
    surname, given = split_name(name)
    if surname and given and is_ascii(name):
        return f"{surname}, {initials(given)}"
    return surname


def fmt_author_mla(name):
    surname, given = split_name(name)
    if surname and given and is_ascii(name):
        return f"{surname}, {given}"
    return name


def author_list(authors, style):
    if not authors:
        return ""
    if style == "gb7714":
        if len(authors) > 3:
            tail = "等" if not all(is_ascii(a) for a in authors) else "et al."
            sep = ", " if all(is_ascii(a) for a in authors) else "，"
            return sep.join(authors[:3]) + tail
        sep = ", " if all(is_ascii(a) for a in authors) else "，"
        return sep.join(authors)
    if style == "apa":
        names = [fmt_author_apa(a) for a in authors]
        if len(names) == 1:
            return names[0]
        if len(names) <= 7:
            return ", ".join(names[:-1]) + " & " + names[-1]
        return ", ".join(names[:6]) + " … " + names[-1]
    names = [fmt_author_mla(a) for a in authors]
    return ", ".join(names)


def join_parts(parts):
    return "".join(p for p in parts if p)


def format_entry(entry, style, index=None):
    t = entry["type"]
    authors = author_list(entry["authors"], style)
    title = entry["title"]
    source = entry["source"]
    year = entry["year"]
    vol = entry.get("volume", "")
    issue = entry.get("issue", "")
    pages = entry.get("pages", "")
    pub = entry.get("publisher", "")
    city = entry.get("city", "")
    doi = entry.get("doi", "")
    url = entry.get("url", "")

    if style == "gb7714":
        label = TYPE_LABEL.get(t, "Z")
        loc = (city + ": " if city else "") + (pub if pub else "")
        if t == "journal":
            tail = f"{source}, {year}" + (f", {vol}" if vol else "")
            if issue:
                tail += f"({issue})"
            if pages:
                tail += f": {pages}"
            text = f"{authors}. {title}[J]. {tail}."
        elif t == "book":
            text = f"{authors}. {title}[M]. "
            text += (f"{loc}, {year}." if loc else f"{year}.")
        elif t == "thesis":
            text = f"{authors}. {title}[D]. "
            text += (f"{loc}, {year}." if loc else f"{source}, {year}." if source else f"{year}.")
        elif t == "conference":
            mid = (f"{loc}, " if loc else "") + year
            text = f"{authors}. {title}[C]//{source}. {mid}"
            text += f": {pages}." if pages else "."
        elif t == "web":
            text = f"{authors}. {title}[EB/OL]. "
            text += (f"{year}." if year else "")
            text += f" {url or source or ''}".rstrip() + "."
        else:
            text = f"{authors}. {title}[Z]. {source}, {year}."
        return (f"[{index}] " if index else "") + text

    if style == "apa":
        if t == "journal":
            text = f"{authors} ({year}). {title}. {source}, {vol}({issue})"
            text += f", {pages}." if pages else "."
            if doi:
                text += f" https://doi.org/{doi}"
            return text
        if t == "book":
            return f"{authors} ({year}). {title}. {pub or source}."
        if t == "web":
            return f"{authors} ({year}). {title}. Retrieved from {url or source}"
        return f"{authors} ({year}). {title}." + (f" {source}." if source else "")

    if style == "mla":
        if t == "journal":
            text = f"{authors}. \"{title}.\" {source}, vol. {vol}, no. {issue}, {year}"
            text += f", pp. {pages}." if pages else "."
            return text
        if t == "book":
            return f"{authors}. {title}. {pub or source}, {year}."
        if t == "web":
            return f"{authors}. \"{title}.\" {url or source}, {year}."
        return (f"{authors}. \"{title}.\" {source}, {year}." if source
                else f"{authors}. \"{title}.\" {year}.")

    # chicago (bibliography)
    if t == "journal":
        text = f"{authors}. \"{title}.\" {source} {vol}, no. {issue} ({year})"
        text += f": {pages}." if pages else "."
        return text
    if t == "book":
        return f"{authors}. {title}. {city + ': ' if city else ''}{pub or source}, {year}."
    if t == "web":
        return f"{authors}. \"{title}.\" {source or 'Accessed'} {year}. {url or ''}".rstrip() + "."
    return f"{authors}. \"{title}.\" {source}, {year}."


def format_references(entries, style, citation_style):
    ordered = list(entries)
    if citation_style == "author_year" and style in ("apa", "mla", "chicago"):
        ordered = sorted(ordered, key=lambda e: ((e["authors"][0] if e["authors"] else ""), e["year"]))
    out = []
    for i, e in enumerate(ordered, 1):
        if citation_style == "numeric":
            out.append(format_entry(e, style, index=i))
        else:
            out.append(format_entry(e, style))
    return out


def citation_marker(entry, citation_style, index=None):
    if citation_style == "numeric":
        return f"[{index}]"
    authors = entry["authors"]
    year = entry["year"]
    if not authors:
        return f"({year})" if year else ""
    first = split_name(authors[0])[0]
    if len(authors) == 1:
        name = first
    elif len(authors) == 2:
        sep = "、" if not is_ascii(authors[0]) else " & "
        name = f"{split_name(authors[0])[0]}{sep}{split_name(authors[1])[0]}"
    else:
        name = (first + ("等" if not is_ascii(first) else " et al."))
    return f"({name}, {year})"


def citation_map(entries, citation_style):
    out = {}
    for i, e in enumerate(entries, 1):
        out[e["key"]] = citation_marker(e, citation_style, index=i)
    return out


# ---------------------------------------------------------------------- check

def spec_texts(spec):
    texts = []
    meta = spec.get("meta", {}) or {}
    texts.append(meta.get("title", ""))
    texts.append(meta.get("abstract", ""))
    texts.append(" ".join(meta.get("keywords") or []))
    for item in spec.get("sections", []):
        if item.get("text"):
            texts.append(item["text"])
        for k in ("headers",):
            for cell in item.get(k) or []:
                texts.append(str(cell))
    return texts


def extract_numeric(text):
    nums = set()
    for m in re.finditer(r"\[(\d+(?:[-,，]\d+)*)\]", text):
        for part in re.split(r"[-,，]", m.group(1)):
            if part.isdigit():
                nums.add(int(part))
    return nums


def extract_author_year(text):
    found = []
    for m in re.finditer(r"[（(]([^（）()]{1,80}?\d{4})[）)]", text):
        inner = m.group(1)
        name_part = re.split(r"[，,]\s*\d{4}", inner)[0].strip()
        year_m = re.search(r"(19\d{2}|20\d{2})", inner)
        if name_part and year_m:
            found.append((name_part, year_m.group(1)))
    return found


def check_references(spec, entries, style, citation_style):
    stats = {
        "count": len(entries),
        "format_issues": [],
        "duplicates": [],
        "cited_missing": [],
        "uncited": [],
        "unverified": [],
    }
    for i, e in enumerate(entries, 1):
        missing = [f for f in ("author", "title", "year")
                   if not e.get(f)]
        if missing:
            stats["format_issues"].append(f"#{i} 缺少字段：{'、'.join(missing)}")
        if not e.get("verified"):
            stats["unverified"].append(f"#{i} {e.get('title', '')[:40]}（示例文献/未验证）")

    seen = {}
    for i, e in enumerate(entries, 1):
        key = (norm_title(e["title"]), e["year"], (e["authors"][0] if e["authors"] else ""))
        if key[0] and key in seen:
            stats["duplicates"].append(f"#{seen[key]} 与 #{i} 疑似重复：{e['title'][:40]}")
        seen[key] = i

    text = "\n".join(spec_texts(spec))
    if citation_style == "numeric":
        cited = extract_numeric(text)
        valid = set(range(1, len(entries) + 1))
        stats["cited_missing"] = [f"[{n}] 正文已引用但文献列表中无对应条目"
                                  for n in sorted(cited - valid)]
        stats["uncited"] = [f"[{n}] {entries[n-1].get('title', '')[:40]}（未被正文引用）"
                            for n in sorted(valid - cited) if n <= len(entries)]
        stats["cited_count"] = len(cited)
    else:
        pairs = extract_author_year(text)
        matched = set()
        for name, year in pairs:
            ok = False
            for i, e in enumerate(entries, 1):
                first = split_name((e["authors"][0] if e["authors"] else ""))[0]
                if first and (first in name or name in first) and e["year"] == year:
                    ok = True
                    matched.add(i)
                    break
            if not ok:
                stats["cited_missing"].append(f"（{name}, {year}）正文已引用但文献列表中无对应条目")
        stats["uncited"] = [f"#{i} {e.get('title', '')[:40]}（未被正文引用）"
                            for i, e in enumerate(entries, 1) if i not in matched]
        stats["cited_count"] = len(pairs)
    return stats


def render_check(stats, style, citation_style):
    ok = not (stats["format_issues"] or stats["duplicates"]
              or stats["cited_missing"] or stats["uncited"])
    lines = [
        "# 参考文献检查报告（ReferenceCheck）",
        "",
        f"- 文献数量：{stats['count']}",
        f"- 引用样式：{'数字编号 [1][2][3]' if citation_style == 'numeric' else '作者年份（张三, 2025）'}",
        f"- 参考文献格式：{style.upper()}",
        f"- 正文引用处数：{stats.get('cited_count', 0)}",
        "",
        "## 格式检查",
        ("✓ 所有条目包含作者、标题、年份" if not stats["format_issues"]
         else f"⚠ {len(stats['format_issues'])} 条缺少字段"),
    ]
    for issue in stats["format_issues"]:
        lines.append(f"- {issue}")
    lines += [
        "",
        "## 重复检查",
        ("✓ 未发现重复" if not stats["duplicates"]
         else f"⚠ 发现 {len(stats['duplicates'])} 组疑似重复"),
    ]
    for d in stats["duplicates"]:
        lines.append(f"- {d}")
    lines += [
        "",
        "## 缺失引用检查",
        ("✓ 正文引用与文献列表完全对应" if not (stats["cited_missing"] or stats["uncited"])
         else f"⚠ 正文引用但列表缺失 {len(stats['cited_missing'])} 处；"
              f"列表存在但正文未引用 {len(stats['uncited'])} 条"),
    ]
    for c in stats["cited_missing"]:
        lines.append(f"- {c}")
    for u in stats["uncited"]:
        lines.append(f"- {u}")
    lines += [
        "",
        "## 疑似不存在文献提示",
        ("✓ 无（所有文献已验证或无需人工确认）" if not stats["unverified"]
         else f"⚠ {len(stats['unverified'])} 篇文献需人工确认（示例文献/未验证）"),
    ]
    for u in stats["unverified"]:
        lines.append(f"- {u}")
    lines += [
        "",
        "## 结论",
        ("✓ 总体合格" if ok else "⚠ 存在需修正项（格式/重复/引用对应）"),
    ]
    return "\n".join(lines) + "\n"


def load_entries(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "entries" in data:
        return data["entries"]
    return data


def annotate_citations(entries, citation_style):
    for i, e in enumerate(entries, 1):
        e["citation"] = citation_marker(e, citation_style, index=i)
    return entries


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Reference management for paper-writer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="Import references into references.json")
    p_import.add_argument("--input", action="append", required=True,
                          help=".bib / .enl / .txt Word list (repeatable)")
    p_import.add_argument("--out", default="references.json")
    p_import.add_argument("--style", choices=STYLES, default="gb7714")
    p_import.add_argument("--citation", choices=CITATIONS, default="numeric")

    p_format = sub.add_parser("format", help="Render references.json as a formatted list")
    p_format.add_argument("--references", required=True)
    p_format.add_argument("--out", default="references_formatted.txt")
    p_format.add_argument("--style", choices=STYLES, default="gb7714")
    p_format.add_argument("--citation", choices=CITATIONS, default="numeric")

    p_check = sub.add_parser("check", help="Check spec vs references -> ReferenceCheck.md")
    p_check.add_argument("--spec", required=True)
    p_check.add_argument("--references", required=True)
    p_check.add_argument("--out", default="ReferenceCheck.md")
    p_check.add_argument("--style", choices=STYLES, default="gb7714")
    p_check.add_argument("--citation", choices=CITATIONS, default="numeric")

    args = parser.parse_args()

    if args.cmd == "import":
        entries = import_refs(args.input)
        entries = annotate_citations(entries, args.citation)
        Path(args.out).write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(json.dumps({"out": args.out, "count": len(entries),
                          "unverified": sum(1 for e in entries if not e["verified"])},
                         ensure_ascii=False, indent=2))
    elif args.cmd == "format":
        entries = load_entries(args.references)
        lines = format_references(entries, args.style, args.citation)
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(json.dumps({"out": args.out, "count": len(lines),
                          "style": args.style, "citation": args.citation},
                         ensure_ascii=False, indent=2))
    elif args.cmd == "check":
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        entries = load_entries(args.references)
        stats = check_references(spec, entries, args.style, args.citation)
        Path(args.out).write_text(render_check(stats, args.style, args.citation),
                                  encoding="utf-8")
        stats["report"] = args.out
        print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
