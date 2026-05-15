#!/usr/bin/env python3
"""
fetch_and_score.py — Phase 1+2: fetch, score, dedup, and select top papers.

Usage:
    python3 fetch_and_score.py > /tmp/daily_papers_top30.json
    python3 fetch_and_score.py --date 2026-02-25 > /tmp/daily_papers_top30.json
    python3 fetch_and_score.py --days 7 > /tmp/daily_papers_top30.json

Stderr: progress logs. Stdout: JSON array of selected papers.
"""

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

_SHARED_DIR = Path(__file__).resolve().parent.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from user_config import daily_papers_config, daily_papers_dir


_CONFIG = daily_papers_config()

KEYWORDS = _CONFIG["keywords"]
NEGATIVE_KEYWORDS = _CONFIG["negative_keywords"]
DOMAIN_BOOST_KEYWORDS = _CONFIG["domain_boost_keywords"]
ARXIV_CATEGORIES = _CONFIG["arxiv_categories"]
MIN_SCORE = _CONFIG["min_score"]
TOP_N = _CONFIG["top_n"]

DAILYPAPERS_DIR = daily_papers_dir()
HISTORY_PATH = DAILYPAPERS_DIR / ".history.json"

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

VENUE_SPECS = [
    {"slug": "isca", "name": "ISCA", "dblp_path": "conf/isca/isca{year}.html", "program_url": "https://iscaconf.org/isca{year}/program/"},
    {"slug": "micro", "name": "MICRO", "dblp_path": "conf/micro/micro{year}.html", "program_url": "https://microarch.org/micro{yy}/program.php"},
    {"slug": "hpca", "name": "HPCA", "dblp_path": "conf/hpca/hpca{year}.html", "program_url": "https://hpca-conf.org/{year}/program/"},
    {"slug": "asplos", "name": "ASPLOS", "dblp_path": "conf/asplos/asplos{year}.html", "program_url": "https://www.asplos-conference.org/asplos{year}/program/"},
    {"slug": "sigcomm", "name": "SIGCOMM", "dblp_path": "conf/sigcomm/sigcomm{year}.html", "program_url": "https://conferences.sigcomm.org/sigcomm/{year}/program/"},
    {"slug": "nsdi", "name": "NSDI", "dblp_path": "conf/nsdi/nsdi{year}.html", "program_url": "https://www.usenix.org/conference/nsdi{yy}/technical-sessions"},
    {"slug": "osdi", "name": "OSDI", "dblp_path": "conf/osdi/osdi{year}.html", "program_url": "https://www.usenix.org/conference/osdi{yy}/technical-sessions"},
    {"slug": "atc", "name": "USENIX ATC", "dblp_path": "conf/usenix/usenix{year}.html", "program_url": "https://www.usenix.org/conference/atc{yy}/technical-sessions"},
    {"slug": "eurosys", "name": "EuroSys", "dblp_path": "conf/eurosys/eurosys{year}.html", "program_url": "https://{year}.eurosys.org/program/"},
    {"slug": "sc", "name": "SC", "dblp_path": "conf/sc/sc{year}.html", "program_url": ""},
    {"slug": "mlsys", "name": "MLSys", "dblp_path": "", "program_url": ""},
]

JOURNAL_SPECS = [
    {"slug": "tpds", "name": "IEEE TPDS", "dblp_path": "journals/tpds/tpds{volume}.html", "base_year": 1990, "base_volume": 1},
    {"slug": "ton", "name": "IEEE/ACM ToN", "dblp_path": "journals/ton/ton{volume}.html", "base_year": 1993, "base_volume": 1},
]


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def score_paper(paper: dict) -> int:
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()
    title_lower = paper.get("title", "").lower()
    venue_text = (paper.get("venue", "") + " " + paper.get("source", "")).lower()

    for neg in NEGATIVE_KEYWORDS:
        if neg in text:
            return -999

    score = 0
    keyword_hits = 0
    for kw in KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in title_lower:
            score += 3
            keyword_hits += 1
        elif kw_lower in text:
            score += 1
            keyword_hits += 1

    domain_hits = sum(1 for kw in DOMAIN_BOOST_KEYWORDS if kw.lower() in text)
    if domain_hits >= 4:
        score += 4
    elif domain_hits >= 2:
        score += 2
    elif domain_hits == 1:
        score += 1

    venue_hits = sum(1 for spec in VENUE_SPECS if spec["slug"] in venue_text or spec["name"].lower() in venue_text)
    if venue_hits:
        score += 2

    systems_phrases = [
        "serving system",
        "runtime system",
        "distributed inference",
        "distributed training",
        "cluster scheduling",
        "memory hierarchy",
        "network stack",
        "datacenter network",
        "collective communication",
    ]
    score += sum(1 for phrase in systems_phrases if phrase in text)

    return score


def retry_delay_from_headers(exc: HTTPError, attempt: int) -> int:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after and retry_after.isdigit():
        return min(int(retry_after), 60)
    return min(5 * (2 ** attempt), 60)


def fetch_url(url: str, timeout: int = 30, retries: int = 2) -> str:
    retry_statuses = {429, 500, 502, 503, 504}
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "daily-papers-bot/2.0"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code in retry_statuses and attempt < retries:
                delay = retry_delay_from_headers(exc, attempt)
                print(
                    f"  [WARN] fetch failed {url}: HTTP {exc.code}; retrying in {delay}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            print(f"  [WARN] fetch failed {url}: {exc}", file=sys.stderr)
            return ""
        except Exception as exc:
            print(f"  [WARN] fetch failed {url}: {exc}", file=sys.stderr)
            return ""
    return ""


def make_base_paper(title: str, authors: str = "", abstract: str = "", url: str = "", **extra) -> dict:
    paper = {
        "title": title,
        "authors": authors,
        "affiliations": "",
        "abstract": abstract,
        "url": url,
        "pdf": extra.pop("pdf", ""),
        "date": extra.pop("date", ""),
        "score": 0,
        "category": extra.pop("category", ""),
        "source": extra.pop("source", ""),
        "venue": extra.pop("venue", ""),
    }
    paper.update(extra)
    return paper


def venue_label(spec: dict, year: int) -> str:
    return f"{spec['name']} {year}"


def display_venue_name(venue: str) -> str:
    normalized = venue.lower()
    names = {
        "eurosys": "EuroSys",
        "sigcomm": "SIGCOMM",
        "isca": "ISCA",
        "micro": "MICRO",
        "hpca": "HPCA",
        "asplos": "ASPLOS",
        "nsdi": "NSDI",
        "osdi": "OSDI",
        "atc": "USENIX ATC",
        "sc": "SC",
        "mlsys": "MLSys",
    }
    return names.get(normalized, venue)


def extract_program_titles(html: str) -> list[str]:
    candidates = []
    for pattern in (
        r"<h[1-4][^>]*>(.*?)</h[1-4]>",
        r"<strong[^>]*>(.*?)</strong>",
        r"<span[^>]*class=[\"'][^\"']*title[^\"']*[\"'][^>]*>(.*?)</span>",
    ):
        for match in re.finditer(pattern, html, re.DOTALL | re.IGNORECASE):
            title = normalize_whitespace(strip_tags(match.group(1)))
            if len(title) < 20 or len(title) > 220:
                continue
            if re.match(r"^(session|keynote|break|poster session|coffee break|panel)\b", title, re.IGNORECASE):
                continue
            if not re.search(r"[A-Za-z]{4,}", title):
                continue
            if title not in candidates:
                candidates.append(title)
    return candidates


def parse_dblp_proceedings_html(html: str, venue: str, year: int) -> list[dict]:
    entries = []
    for match in re.finditer(r"(<li class=\"entry [^\"]*?\".*?)(?=<li class=\"entry |\Z)", html, re.DOTALL):
        block = match.group(1)
        title_match = re.search(r"<span class=\"title\"[^>]*>(.*?)</span>", block, re.DOTALL)
        if not title_match:
            continue

        title = normalize_whitespace(strip_tags(title_match.group(1)))
        tail = block[title_match.end():title_match.end() + 8]
        if tail.lstrip().startswith(".") and not title.endswith("."):
            title += "."
        if not title:
            continue

        authors = [
            normalize_whitespace(strip_tags(author))
            for author in re.findall(r"<span itemprop=\"author\"[^>]*>(.*?)</span>", block, re.DOTALL)
        ]
        links = re.findall(r"<a href=\"([^\"]+)\"", block)
        url = next((link for link in links if "doi.org" in link or "arxiv.org" in link), "")

        entries.append(
            make_base_paper(
                title=title,
                authors=", ".join(author for author in authors if author),
                url=url,
                source="dblp",
                venue=f"{display_venue_name(venue)} {year}",
                date=f"{year}-01-01",
            )
        )

    return entries


def parse_journal_html(html: str, journal_name: str, year: int) -> list[dict]:
    entries = []
    for paper in parse_dblp_proceedings_html(html, venue=journal_name, year=year):
        paper["source"] = "dblp-journal"
        paper["venue"] = journal_name
        entries.append(paper)
    return entries


def fetch_dblp_papers(target_date, years_back: int = 2) -> list[dict]:
    papers = []
    seen_titles = set()
    current_year = target_date.year

    for spec in VENUE_SPECS:
        if not spec["dblp_path"]:
            continue
        for year in range(current_year, current_year - years_back, -1):
            url = f"https://dblp.org/db/{spec['dblp_path'].format(year=year)}"
            print(f"  Fetching DBLP {spec['name']} {year}...", file=sys.stderr)
            html = fetch_url(url, timeout=30)
            if not html:
                continue
            parsed = parse_dblp_proceedings_html(html, venue=spec["name"], year=year)
            for paper in parsed:
                title_key = paper["title"].lower()
                if title_key in seen_titles:
                    continue
                paper["score"] = score_paper(paper)
                if paper["score"] >= MIN_SCORE:
                    seen_titles.add(title_key)
                    papers.append(paper)

    for spec in JOURNAL_SPECS:
        for year in range(current_year, current_year - years_back, -1):
            volume = spec["base_volume"] + (year - spec["base_year"])
            url = f"https://dblp.org/db/{spec['dblp_path'].format(volume=volume)}"
            print(f"  Fetching DBLP {spec['name']} volume {volume}...", file=sys.stderr)
            html = fetch_url(url, timeout=30)
            if not html:
                continue
            for paper in parse_journal_html(html, journal_name=spec["name"], year=year):
                title_key = paper["title"].lower()
                if title_key in seen_titles:
                    continue
                paper["score"] = score_paper(paper)
                if paper["score"] >= MIN_SCORE:
                    seen_titles.add(title_key)
                    papers.append(paper)

    print(f"  DBLP: {len(papers)} papers after scoring", file=sys.stderr)
    return papers


def fetch_conference_program_papers(target_date) -> list[dict]:
    now = datetime.now().date()
    if (now - target_date).days > 56:
        return []

    papers = []
    seen_titles = set()
    year = target_date.year
    yy = str(year)[-2:]

    for spec in VENUE_SPECS:
        if not spec["program_url"]:
            continue
        url = spec["program_url"].format(year=year, yy=yy)
        print(f"  Fetching program page {spec['name']} {year}...", file=sys.stderr)
        html = fetch_url(url, timeout=20)
        if not html:
            continue
        for title in extract_program_titles(html):
            title_key = title.lower()
            if title_key in seen_titles:
                continue
            paper = make_base_paper(
                title=title,
                url=url,
                source="conference-program",
                venue=venue_label(spec, year),
                date=f"{year}-01-01",
            )
            paper["score"] = score_paper(paper)
            if paper["score"] >= MIN_SCORE:
                seen_titles.add(title_key)
                papers.append(paper)

    print(f"  Program pages: {len(papers)} papers after scoring", file=sys.stderr)
    return papers


def fetch_semantic_scholar_papers(target_date, days: int = 1) -> list[dict]:
    query = quote("LLM serving OR GPU cluster OR RDMA OR accelerator OR distributed systems")
    limit = min(30 * days, 100)
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={query}&fields=title,abstract,authors,year,venue,url,externalIds&limit={limit}"
    )
    print("  Fetching Semantic Scholar fallback...", file=sys.stderr)
    raw = fetch_url(url, timeout=30)
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("  [WARN] bad JSON from Semantic Scholar", file=sys.stderr)
        return []

    papers = []
    current_year = target_date.year
    for item in payload.get("data", []):
        year = item.get("year")
        if year and year < current_year - 2:
            continue
        authors = ", ".join(
            author.get("name", "").strip()
            for author in item.get("authors", [])
            if isinstance(author, dict) and author.get("name")
        )
        external_ids = item.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv", "")
        url = item.get("url", "")
        paper = make_base_paper(
            title=item.get("title", ""),
            authors=authors,
            abstract=item.get("abstract", "") or "",
            url=url,
            pdf=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
            source="semantic-scholar",
            venue=item.get("venue", "") or "Semantic Scholar",
            date=f"{year}-01-01" if year else "",
        )
        paper["score"] = score_paper(paper)
        if paper["score"] >= MIN_SCORE:
            papers.append(paper)

    print(f"  Semantic Scholar: {len(papers)} papers after scoring", file=sys.stderr)
    return papers


def fetch_arxiv_papers(start_date=None, end_date=None, days: int = 1) -> list[dict]:
    max_results = min(400 * days, 3000)
    cats = "+OR+".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    url = (
        f"https://export.arxiv.org/api/query?"
        f"search_query=({cats})"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    )

    timeout = max(60, 30 * days)
    print(f"  Fetching arXiv (max_results={max_results}, timeout={timeout}s)...", file=sys.stderr)
    xml_text = fetch_url(url, timeout=timeout)
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        print(f"  [WARN] arXiv XML parse error: {exc}", file=sys.stderr)
        return []

    papers = []
    filtered_by_date = 0
    for entry in root.findall("atom:entry", ATOM_NS):
        title_el = entry.find("atom:title", ATOM_NS)
        summary_el = entry.find("atom:summary", ATOM_NS)
        published_el = entry.find("atom:published", ATOM_NS)
        id_el = entry.find("atom:id", ATOM_NS)

        if title_el is None or summary_el is None:
            continue

        title = normalize_whitespace(title_el.text or "")
        abstract = normalize_whitespace(summary_el.text or "")
        entry_url = (id_el.text or "").strip() if id_el is not None else ""
        date = (published_el.text or "")[:10] if published_el is not None else ""

        if days > 1 and start_date and end_date and date:
            try:
                pub_date = datetime.strptime(date, "%Y-%m-%d").date()
                if pub_date < start_date or pub_date > end_date:
                    filtered_by_date += 1
                    continue
            except ValueError:
                pass

        author_els = entry.findall("atom:author", ATOM_NS)
        names = []
        affiliations = set()
        for author in author_els:
            name_el = author.find("atom:name", ATOM_NS)
            if name_el is not None and name_el.text:
                names.append(name_el.text.strip())
            for aff_el in author.findall("arxiv:affiliation", ATOM_NS):
                if aff_el.text and aff_el.text.strip():
                    affiliations.add(aff_el.text.strip())

        cat_el = entry.find("arxiv:primary_category", ATOM_NS)
        category = cat_el.get("term", "") if cat_el is not None else ""
        arxiv_id = entry_url.split("/abs/")[-1] if "/abs/" in entry_url else ""
        paper = make_base_paper(
            title=title,
            authors=", ".join(names),
            abstract=abstract,
            url=entry_url,
            pdf=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
            date=date,
            category=category,
            source="arxiv",
            venue="arXiv",
            affiliations=", ".join(sorted(affiliations)) if affiliations else "",
        )
        paper["score"] = score_paper(paper)
        if paper["score"] >= 0:
            papers.append(paper)

    print(
        f"  arXiv: {len(papers)} papers after scoring (from {len(root.findall('atom:entry', ATOM_NS))} parsed, {filtered_by_date} filtered by date)",
        file=sys.stderr,
    )
    return papers


def extract_arxiv_id(text: str) -> str:
    """Pull an arXiv id from a string.

    Accepts either an arXiv URL / ``arXiv:xxxx.yyyy`` reference, or a raw
    bare id like ``2501.01234`` (or ``2501.01234v2``). Refuses to match
    digit runs inside unrelated identifiers such as DOIs."""
    text = (text or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "arxiv" in lowered:
        match = re.search(r"(\d{4}\.\d{4,5})", text)
        return match.group(1) if match else ""
    match = re.fullmatch(r"(\d{4}\.\d{4,5})(?:v\d+)?", text)
    return match.group(1) if match else ""


_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)


def extract_doi(text: str) -> str:
    match = _DOI_RE.search(text or "")
    if not match:
        return ""
    return match.group(1).rstrip(".,);").lower()


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def paper_lookup_keys(paper: dict) -> set[str]:
    """Return all lookup keys identifying a paper. Used for history dedup,
    where the same paper may be referenced by arxiv id, DOI, or normalized
    title across different sources / history schemas."""
    keys: set[str] = set()
    url = paper.get("url", "") or ""
    title = paper.get("title", "") or ""
    explicit_id = str(paper.get("id", "") or "")
    explicit_doi = paper.get("doi", "") or ""

    arxiv = extract_arxiv_id(url) or extract_arxiv_id(explicit_id)
    if arxiv:
        keys.add(f"arxiv:{arxiv}")

    for candidate in (explicit_doi, url, explicit_id):
        doi = extract_doi(candidate)
        if doi:
            keys.add(f"doi:{doi}")
            break

    fallback_title = title or (explicit_id if not explicit_id.startswith(("http", "10.")) else "")
    norm = normalize_title(fallback_title)
    if norm:
        keys.add(f"title:{norm}")

    return keys


def dedup_key(paper: dict) -> str:
    """Single strongest key for in-memory merge dedup. Prefers arxiv > doi > title."""
    keys = paper_lookup_keys(paper)
    for prefix in ("arxiv:", "doi:", "title:"):
        for key in keys:
            if key.startswith(prefix):
                return key
    return f"title:{(paper.get('title') or '').strip().lower()}"


def apply_age_decay(papers: list[dict], target_date) -> None:
    """Reduce score for older papers so DBLP back-catalog cannot overpower
    today's arXiv. Mutates papers in place."""
    for paper in papers:
        date_str = paper.get("date", "") or ""
        if not date_str:
            continue
        try:
            pdate = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        age_days = (target_date - pdate).days
        if age_days <= 30:
            continue
        if age_days <= 180:
            factor = 0.75
        elif age_days <= 365:
            factor = 0.55
        else:
            factor = 0.35
        paper["score"] = int(paper["score"] * factor)


def select_with_quota(candidates: list[dict], top_n: int, dblp_max_ratio: float = 0.4) -> list[dict]:
    """Cap how many slots DBLP / venue scrapes can take, so today's arXiv
    is not crowded out by year-old conference papers."""
    dblp_max = max(1, int(top_n * dblp_max_ratio))
    arxiv = [p for p in candidates if p.get("source") == "arxiv"]
    others = [p for p in candidates if p.get("source") != "arxiv"]
    others = others[:dblp_max]
    combined = arxiv + others
    combined.sort(key=lambda item: item["score"], reverse=True)
    return combined[:top_n]


def load_history() -> list[dict]:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return []


def load_fallback_ids(days: int = 7) -> set[str]:
    ids = set()
    today = datetime.now().date()
    for offset in range(1, days + 1):
        fpath = DAILYPAPERS_DIR / f"{(today - timedelta(days=offset)).isoformat()}-论文推荐.md"
        if not fpath.exists():
            continue
        try:
            text = fpath.read_text()
        except IOError:
            continue
        for match in re.finditer(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", text):
            ids.add(match.group(1))
    return ids


def build_history_index(history: list[dict]) -> tuple[set[str], dict[str, str]]:
    """Build a set of all lookup keys present in history plus a key→date map.
    Tolerant of history rows that use title, DOI, or arxiv URL as the id."""
    keys: set[str] = set()
    key_dates: dict[str, str] = {}
    for item in history:
        raw_id = str(item.get("id", "") or "")
        item_keys = paper_lookup_keys(
            {
                "url": raw_id if raw_id.startswith("http") else "",
                "doi": raw_id if raw_id.startswith("10.") else "",
                "title": item.get("title", "") or (raw_id if not raw_id.startswith(("http", "10.")) else ""),
                "id": raw_id,
            }
        )
        paper_date = item.get("date", "") or ""
        for key in item_keys:
            keys.add(key)
            if paper_date and (key not in key_dates or paper_date < key_dates[key]):
                key_dates[key] = paper_date
    return keys, key_dates


def merge_and_dedup(primary_papers: list[dict], arxiv_papers: list[dict], target_date, days: int = 1, top_n: int = TOP_N) -> list[dict]:
    by_key = {}
    for paper in primary_papers + arxiv_papers:
        key = dedup_key(paper)
        if key not in by_key or paper["score"] > by_key[key]["score"]:
            by_key[key] = paper

    print(f"  Merged: {len(by_key)} unique papers", file=sys.stderr)

    apply_age_decay(list(by_key.values()), target_date)

    if days > 1:
        candidates = [paper for paper in by_key.values() if paper["score"] >= MIN_SCORE]
        top = select_with_quota(candidates, top_n)
        print(f"  Multi-day mode: {len(top)} papers", file=sys.stderr)
        return top

    history = load_history()
    history_keys, history_dates = build_history_index(history)

    if len(history) < 10:
        for paper_id in load_fallback_ids():
            history_keys.add(f"arxiv:{paper_id}")
            history_dates.setdefault(f"arxiv:{paper_id}", "unknown")

    deduped = {}
    removed = 0
    for key, paper in by_key.items():
        if paper_lookup_keys(paper) & history_keys:
            removed += 1
            continue
        deduped[key] = paper

    print(f"  After history dedup: {len(deduped)} (removed {removed})", file=sys.stderr)

    candidates = [paper for paper in deduped.values() if paper["score"] >= MIN_SCORE]
    top = select_with_quota(candidates, top_n)

    if len(top) < top_n and removed > 0:
        backfill = []
        for paper in by_key.values():
            paper_keys = paper_lookup_keys(paper)
            matched_keys = paper_keys & history_keys
            if not matched_keys or paper["score"] < MIN_SCORE:
                continue
            paper = dict(paper)
            paper["is_re_recommend"] = True
            paper["last_recommend_date"] = next(
                (history_dates.get(k, "unknown") for k in matched_keys),
                "unknown",
            )
            backfill.append(paper)
        backfill.sort(key=lambda item: item["score"], reverse=True)
        needed = top_n - len(top)
        if needed > 0 and backfill:
            top.extend(backfill[:needed])
            print(f"  Back-filled {min(needed, len(backfill))} from history", file=sys.stderr)

    print(f"  Final: {len(top)} papers", file=sys.stderr)
    return top


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--days", type=int, default=1, help="Number of days to fetch (default: 1)")
    args = parser.parse_args()

    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else datetime.now().date()
    )
    days = max(1, args.days)
    start_date = target_date - timedelta(days=days - 1)
    top_n = TOP_N * days

    print(
        f"[fetch_and_score] {target_date}"
        + (f", days={days} [{start_date} ~ {target_date}], top_n={top_n}" if days > 1 else ""),
        file=sys.stderr,
    )

    primary_papers = fetch_dblp_papers(target_date)
    if not primary_papers:
        primary_papers = fetch_conference_program_papers(target_date)

    arxiv_papers = fetch_arxiv_papers(start_date, target_date, days)

    if len(primary_papers) + len(arxiv_papers) < 20:
        semantic_scholar_papers = fetch_semantic_scholar_papers(target_date, days=days)
        primary_papers.extend(semantic_scholar_papers)

    top = merge_and_dedup(primary_papers, arxiv_papers, target_date, days=days, top_n=top_n)

    json.dump(top, sys.stdout, ensure_ascii=False, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
