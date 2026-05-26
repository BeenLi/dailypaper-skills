#!/usr/bin/env python3
"""Batch-enrich arXiv papers with metadata from HTML/abs pages.

Usage:
    cat /tmp/daily_papers_top30.json | python3 enrich_papers.py > /tmp/daily_papers_enriched.json

Input:  JSON array via stdin (format from daily-papers Phase 2)
Output: JSON array via stdout with enriched fields added

Architecture:
    - asyncio + subprocess curl for concurrent HTTP requests
    - Semaphore(10) to avoid hammering arXiv
    - Pure regex HTML parsing (no WebFetch / no external deps)
    - Per-request timeout via curl --max-time (no Python-level per-paper timeout)
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import quote

SEMAPHORE_LIMIT = 10
CURL_TIMEOUT = 30

# ── Stop words for method_names extraction ──────────────────────────────────
METHOD_STOP = {
    # Section headings
    "Abstract", "Introduction", "Method", "Methods", "Methodology",
    "Results", "Conclusion", "Conclusions", "Discussion", "Experiments",
    "Experiment", "Evaluation", "Background", "Appendix", "Supplementary",
    "References", "Related", "Overview", "Preliminaries", "Framework",
    "Acknowledgements", "Acknowledgments",
    # Conferences / venues
    "CVPR", "ICCV", "ECCV", "NeurIPS", "ICML", "ICLR", "IEEE", "AAAI",
    "IJCAI", "SIGCHI", "SIGGRAPH", "ICRA", "IROS", "CoRL", "RSS",
    "WACV", "BMVC", "ACCV", "MICCAI", "ACL", "EMNLP", "NAACL",
    # Common abbreviations (not method names)
    "RGB", "GPU", "CPU", "TPU", "CNN", "MLP", "SGD", "ADAM", "GAN",
    "RNN", "LSTM", "GRU", "API", "URL", "HTML", "PDF", "JSON", "XML",
    "FPS", "IoU", "MAP", "FID", "PSNR", "SSIM", "LPIPS", "MSE", "MAE",
    "BCE", "CE", "KL", "GNN", "VAE", "ELBO", "EM",
    "SoTA", "SOTA", "TODO", "NOTE", "TBD",
    # Generic terms
    "Table", "Figure", "Section", "Eq", "Equation", "Algorithm",
    "Step", "Phase", "Stage", "Layer", "Block", "Module", "Head",
    "Loss", "Input", "Output", "Data", "Model", "Network",
    "Training", "Testing", "Inference", "Baseline", "Ablation",
    # Roman numerals
    "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII",
    # Common LaTeX / HTML artifacts
    "LaTeX", "BibTeX", "ArXiv",
}

# ── Systems eval signal keywords ────────────────────────────────────────────
HARDWARE_EVAL_KEYWORDS = [
    "gpu", "cpu", "nic", "fpga", "tpu", "server", "node", "cluster",
    "a100", "h100", "h800", "l40s", "rtx 4090", "rtx4090", "rtx 5090", "rtx5090",
    "tensor core", "rdma", "roce", "infiniband", "pcie", "hbm",
]

END_TO_END_EVAL_KEYWORDS = [
    "end-to-end", "end to end", "serving evaluation", "request latency",
    "tokens per second", "throughput", "tail latency", "ttft", "e2e",
    "full system", "online serving", "serving system", "inference engine",
]

REAL_WORKLOAD_KEYWORDS = [
    "production trace", "real trace", "cluster trace", "datacenter trace",
    "serving trace", "online workload", "real workload", "workload trace",
    "trace-driven", "trace driven", "replay trace",
]

SYNTHETIC_WORKLOAD_KEYWORDS = [
    "synthetic workload", "synthetic trace", "simulated workload",
    "generated workload", "random workload", "toy workload",
]

# ── Institution keywords for HTML affiliation extraction ────────────────────
INST_KEYWORDS = [
    "university", "universite", "università", "universität",
    "institute", "laboratory", "college", "school of",
    "center for", "centre for", "academy", "polytechnic",
    "department of", "faculty of", "research center", "research centre",
    "national lab",
    "google", "nvidia", "meta ai", "meta platforms", "microsoft",
    "deepmind", "openai", "alibaba", "tencent", "baidu", "bytedance",
    "amazon", "apple", "samsung", "huawei", "intel", "qualcomm",
    "adobe", "salesforce", "ibm research", "uber", "waymo", "toyota",
    "sony", "bosch", "damo academy",
    "mit ", "csail", "stanford", "berkeley", "cmu", "caltech",
    "eth zurich", "eth zürich", "epfl", "kaist", "inria", "mpi ",
    "fair ", "max planck", "cnrs",
    "tsinghua", "peking", "westlake", "hkust", "hku ", "fudan",
    "sjtu", "zju", "nju", "ustc", "cuhk", "shanghaitech",
    "chinese academy", "shanghai ai", "nanjing university",
    "nankai", "south china",
]


# ══════════════════════════════════════════════════════════════════════════════
# HTTP helpers
# ══════════════════════════════════════════════════════════════════════════════

async def curl_fetch(url: str, sem: asyncio.Semaphore, timeout: int = CURL_TIMEOUT,
                     retries: int = 3) -> str:
    """Fetch URL content using curl subprocess with retry. Returns empty string on failure."""
    for attempt in range(1, retries + 1):
        async with sem:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "curl", "-sL", "--max-time", str(timeout), url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
                content = stdout.decode("utf-8", errors="replace") if stdout else ""
                if content:
                    return content
            except (asyncio.TimeoutError, Exception) as e:
                print(f"  [curl] attempt {attempt}/{retries} failed {url}: {e}", file=sys.stderr)
        if attempt < retries:
            await asyncio.sleep(3 * attempt)  # 3s, 6s
    return ""


async def curl_fetch_bytes(url: str, sem: asyncio.Semaphore, timeout: int = CURL_TIMEOUT,
                           retries: int = 3) -> bytes:
    """Fetch URL content as bytes using curl subprocess with retry."""
    for attempt in range(1, retries + 1):
        async with sem:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "curl", "-sL", "--max-time", str(timeout), url,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
                if stdout:
                    return stdout
            except (asyncio.TimeoutError, Exception) as e:
                print(f"  [curl-bytes] attempt {attempt}/{retries} failed {url}: {e}", file=sys.stderr)
        if attempt < retries:
            await asyncio.sleep(3 * attempt)
    return b""



# ══════════════════════════════════════════════════════════════════════════════
# HTML regex extractors
# ══════════════════════════════════════════════════════════════════════════════

def strip_tags(html: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", html)


def extract_figure_url(html: str, arxiv_id: str) -> str:
    """Extract the first non-icon figure image URL from HTML."""
    figures = re.findall(r"<figure[^>]*>.*?<img[^>]+src=[\"']([^\"'>]+)[\"']", html, re.DOTALL)
    skip_words = ["icon", "logo", "badge", "inline", "orcid", "creative"]
    for fig in figures:
        if any(skip in fig.lower() for skip in skip_words):
            continue
        url = fig
        if url.startswith("/"):
            url = "https://arxiv.org" + url
        elif not url.startswith("http"):
            url = "https://arxiv.org/html/" + url
        return url
    return ""


def extract_authors_html(html: str) -> list[str]:
    """Extract authors from ltx_personname spans."""
    matches = re.findall(r'class="ltx_personname"[^>]*>(.*?)</span>', html, re.DOTALL)
    authors = []
    for m in matches:
        name = strip_tags(m).strip()
        # Skip if it looks like an affiliation or footnote
        if name and len(name) < 80 and not any(kw in name.lower() for kw in ["university", "institute", "department"]):
            authors.append(name)
    return authors


def extract_affiliations_html(html: str) -> list[str]:
    """Extract affiliations from HTML paper using multiple strategies."""
    affils = set()

    # Strategy 1: structured class elements (ltx_role_affil, ltx_contact)
    # Search up to abstract or first 80k chars (some pages have long headers)
    abstract_pos = html.find("ltx_abstract")
    search_end = abstract_pos if abstract_pos > 0 else min(len(html), 80000)
    search_region = html[:search_end]
    for cls in ("ltx_role_affil", "ltx_contact"):
        for m in re.finditer(
            rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)</(?:span|div|p|td)',
            search_region, re.DOTALL
        ):
            text = strip_tags(m.group(1)).strip(" ,;.")
            if text and 3 < len(text) < 500:
                affils.add(text)

    # Strategy 2: header region plain text (between <article> and ltx_abstract)
    article_start = html.find("<article")
    abstract_start = html.find("ltx_abstract")
    if article_start >= 0 and abstract_start > article_start:
        header_text = strip_tags(html[article_start:abstract_start])
        for line in header_text.split("\n"):
            line = line.strip()
            if not line or len(line) < 5 or len(line) > 500:
                continue
            if any(kw in line.lower() for kw in INST_KEYWORDS):
                affils.add(line.strip(" ,;."))

    return list(affils)


def extract_section_headers(html: str) -> list[str]:
    """Extract h2/h3 section headers."""
    headers = []
    for m in re.finditer(r"<h[23][^>]*>(.*?)</h[23]>", html, re.DOTALL):
        text = strip_tags(m.group(1)).strip()
        text = re.sub(r"^\d+(\.\d+)*\.?\s*", "", text)  # remove "1.2.3 " prefix
        if text and len(text) < 200:
            headers.append(text)
    return headers[:25]


def extract_captions(html: str) -> list[str]:
    """Extract figure/table captions of reasonable length."""
    captions = []
    for m in re.finditer(r"<(?:figcaption|caption)[^>]*>(.*?)</(?:figcaption|caption)>", html, re.DOTALL):
        text = strip_tags(m.group(1)).strip()
        text = re.sub(r"\s+", " ", text)
        if 10 <= len(text) <= 200:
            captions.append(text)
    return captions[:8]


def extract_has_hardware_eval(html: str) -> bool:
    """Check if HTML mentions concrete hardware evaluation targets."""
    html_lower = html.lower()
    return any(kw in html_lower for kw in HARDWARE_EVAL_KEYWORDS)


def extract_has_end_to_end_eval(html: str) -> bool:
    """Check if HTML mentions end-to-end or serving-system level evaluation."""
    html_lower = html.lower()
    return any(kw in html_lower for kw in END_TO_END_EVAL_KEYWORDS)


def extract_has_real_workload(html: str) -> bool:
    """Check if HTML mentions real traces/workloads rather than synthetic ones."""
    html_lower = html.lower()
    if not any(kw in html_lower for kw in REAL_WORKLOAD_KEYWORDS):
        return False
    if any(kw in html_lower for kw in SYNTHETIC_WORKLOAD_KEYWORDS):
        return False
    return True


def extract_method_names(html: str, paper_title: str) -> list[str]:
    """Extract method/model names from HTML text using CamelCase + ALLCAPS patterns."""
    text = strip_tags(html)

    # CamelCase: FlashInfer, TensorRT, ControlNet, MuJoCo
    camel = re.findall(r"\b([A-Z][a-z]+(?:[A-Z][a-z]*)+(?:V?\d+)?)\b", text)
    # ALLCAPS with optional version: DDPM, SAM-2, GPT-4, RT-2
    allcaps = re.findall(r"\b([A-Z]{2,}(?:[-_]\d+)?)\b", text)
    # CamelCase with numbers: GPT4o, Llama3
    camel_num = re.findall(r"\b([A-Z][a-z]+[A-Z][a-z]*\d+[a-z]?)\b", text)
    # Hyphenated: Diffusion-Policy, Stable-Diffusion
    hyphenated = re.findall(r"\b([A-Z][a-z]+-[A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b", text)

    all_names = camel + allcaps + camel_num + hyphenated
    cnt = Counter(all_names)

    # Build stop set including title words
    title_words = set(re.findall(r"\b[A-Za-z]+\b", paper_title))
    stop = METHOD_STOP | {w for w in title_words if len(w) >= 3}

    method_names = []
    seen = set()
    for name, count in cnt.most_common(40):
        if count < 2:
            continue
        if name in stop:
            continue
        if len(name) < 2:
            continue
        name_lower = name.lower()
        if name_lower in seen:
            continue
        seen.add(name_lower)
        method_names.append(name)
        if len(method_names) >= 20:
            break

    return method_names


def extract_primary_method_name(html: str, paper_title: str) -> str:
    """Extract a conservative single primary system/method name.

    Rules:
    1. If the title has a prefix before ':' and it looks like a compact system/method name, use it.
    2. Otherwise, look for high-confidence system-like tokens in the title only.
    3. If still not confident, fall back to the full title without trailing punctuation.
    """
    title = (paper_title or "").strip()
    if not title:
        return ""

    title_no_trailing = title.rstrip(".:; ")
    if ":" in title:
        prefix = title.split(":", 1)[0].strip().rstrip(".:; ")
        if 2 <= len(prefix) <= 40:
            return prefix

    title_tokens = extract_method_names(title, title_no_trailing)
    if len(title_tokens) == 1:
        return title_tokens[0]

    return title_no_trailing


def extract_method_summary(html: str) -> str:
    """Extract method description from Method/Approach sections (300-500 chars)."""
    # Strategy: find h2/h3 headers containing Method/Approach/Framework/Proposed,
    # then extract text until the next h2/h3.
    # Note: headers may contain inner tags like <span>, so we use .*? not [^<]*
    section_text = ""

    # Primary: find content after Method/Approach header until next header
    m = re.search(
        r"<h[23][^>]*>.*?(?:Method|Approach|Framework|Proposed).*?</h[23]>(.*?)(?:<h[23]|$)",
        html, re.DOTALL | re.IGNORECASE
    )
    if m:
        section_text = strip_tags(m.group(1))

    if not section_text:
        # Last resort: try Introduction's last paragraphs
        m = re.search(
            r"<h[23][^>]*>.*?Introduction.*?</h[23]>(.*?)(?:<h[23]|$)",
            html, re.DOTALL | re.IGNORECASE
        )
        if m:
            intro_text = strip_tags(m.group(1))
            paragraphs = [p.strip() for p in intro_text.split("\n\n") if p.strip()]
            # Take last 2 paragraphs (usually contain method overview)
            section_text = "\n".join(paragraphs[-2:]) if paragraphs else ""

    if not section_text:
        return ""

    # Clean up
    section_text = re.sub(r"\s+", " ", section_text).strip()
    # Remove citation markers like [1], [2,3]
    section_text = re.sub(r"\s*\[\d+(?:,\s*\d+)*\]", "", section_text)

    # Truncate to ~300-500 chars at sentence boundary
    if len(section_text) > 500:
        # Find sentence end near 500 chars
        end = section_text.rfind(". ", 300, 550)
        if end > 0:
            section_text = section_text[:end + 1]
        else:
            section_text = section_text[:500].rsplit(" ", 1)[0] + "..."

    return section_text if len(section_text) >= 100 else ""


# ══════════════════════════════════════════════════════════════════════════════
# Abs page fallback extractor
# ══════════════════════════════════════════════════════════════════════════════

def extract_from_abs(html: str) -> dict:
    """Extract authors and affiliations from arxiv abs page meta tags."""
    authors = re.findall(r'<meta\s+name="citation_author"\s+content="([^"]+)"', html)
    authors = [a.strip() for a in authors if a.strip()]
    affils = set()
    for m in re.findall(r'<meta\s+name="citation_author_institution"\s+content="([^"]+)"', html):
        if m.strip():
            affils.add(m.strip())
    return {"authors": authors, "affiliations": list(affils)}


def normalize_title(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def titles_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    na = normalize_title(a)
    nb = normalize_title(b)
    return na == nb or na in nb or nb in na


def summarize_abstract(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) < 80:
        return ""
    if len(text) > 500:
        end = text.rfind(". ", 300, 550)
        if end > 0:
            text = text[:end + 1]
        else:
            text = text[:500].rsplit(" ", 1)[0] + "..."
    return text


def extract_meta_tags(html: str) -> dict:
    meta = {}
    for name, content in re.findall(
        r'<meta[^>]+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    ):
        meta[name.lower()] = content.strip()
    return meta


def extract_doi(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", value, re.IGNORECASE)
    return match.group(1) if match else ""


def reconstruct_openalex_abstract(inverted_index: dict) -> str:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""

    max_pos = -1
    for positions in inverted_index.values():
        if isinstance(positions, list) and positions:
            max_pos = max(max_pos, max(positions))
    if max_pos < 0:
        return ""

    words = [""] * (max_pos + 1)
    for token, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if 0 <= pos <= max_pos:
                words[pos] = token

    text = " ".join(word for word in words if word).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


async def search_arxiv_by_title(title: str, sem: asyncio.Semaphore) -> dict:
    query = quote(f'ti:"{title}"')
    url = (
        "https://export.arxiv.org/api/query"
        f"?search_query={query}&start=0&max_results=5"
    )
    xml_text = await curl_fetch(url, sem)
    if not xml_text:
        return {}

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    best = {}
    for entry in root.findall("atom:entry", {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}):
        title_el = entry.find("atom:title", {"atom": "http://www.w3.org/2005/Atom"})
        if title_el is None or not titles_match(title, title_el.text or ""):
            continue
        summary_el = entry.find("atom:summary", {"atom": "http://www.w3.org/2005/Atom"})
        published_el = entry.find("atom:published", {"atom": "http://www.w3.org/2005/Atom"})
        id_el = entry.find("atom:id", {"atom": "http://www.w3.org/2005/Atom"})
        authors = []
        affiliations = []
        for author in entry.findall("atom:author", {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}):
            name_el = author.find("atom:name", {"atom": "http://www.w3.org/2005/Atom"})
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())
            for aff_el in author.findall("arxiv:affiliation", {"arxiv": "http://arxiv.org/schemas/atom"}):
                if aff_el.text and aff_el.text.strip():
                    affiliations.append(aff_el.text.strip())
        arxiv_url = id_el.text.strip() if id_el is not None and id_el.text else ""
        arxiv_id_match = re.search(r"(\d{4}\.\d{4,5})", arxiv_url)
        best = {
            "title": re.sub(r"\s+", " ", title_el.text or "").strip(),
            "abstract": re.sub(r"\s+", " ", summary_el.text or "").strip() if summary_el is not None else "",
            "authors": authors,
            "affiliations": list(dict.fromkeys(affiliations)),
            "url": arxiv_url,
            "pdf": f"https://arxiv.org/pdf/{arxiv_id_match.group(1)}" if arxiv_id_match else "",
            "date": (published_el.text or "")[:10] if published_el is not None else "",
            "arxiv_id": arxiv_id_match.group(1) if arxiv_id_match else "",
        }
        break
    return best


async def fetch_doi_metadata(url_or_doi: str, sem: asyncio.Semaphore) -> dict:
    doi = extract_doi(url_or_doi)
    if not doi:
        return {}

    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    raw = await curl_fetch(url, sem)
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    message = payload.get("message") or {}
    title_list = message.get("title") or []
    abstract = message.get("abstract") or ""
    abstract = re.sub(r"</?jats:[^>]+>", " ", abstract)
    abstract = re.sub(r"<[^>]+>", " ", abstract)
    abstract = re.sub(r"\s+", " ", abstract).strip()

    authors = []
    affiliations = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        given = (author.get("given") or "").strip()
        family = (author.get("family") or "").strip()
        name = " ".join(part for part in (given, family) if part)
        if name:
            authors.append(name)
        for aff in author.get("affiliation") or []:
            if isinstance(aff, dict) and aff.get("name"):
                affiliations.append(aff["name"].strip())

    resource = message.get("resource") or {}
    primary_url = resource.get("primary", {}).get("URL", "") if isinstance(resource, dict) else ""

    return {
        "doi": doi,
        "title": title_list[0].strip() if title_list else "",
        "abstract": abstract,
        "authors": authors,
        "affiliations": list(dict.fromkeys(a for a in affiliations if a)),
        "url": primary_url or f"https://doi.org/{doi}",
    }


async def fetch_doi_landing_metadata(url_or_doi: str, sem: asyncio.Semaphore) -> dict:
    if not url_or_doi:
        return {}
    url = url_or_doi
    if not url.startswith("http"):
        url = f"https://doi.org/{url_or_doi}"
    html = await curl_fetch(url, sem)
    if not html:
        return {}

    meta = extract_meta_tags(html)
    authors = []
    affiliations = []
    for content in re.findall(
        r'<meta[^>]+name=["\']citation_author["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    ):
        authors.append(content.strip())
    for content in re.findall(
        r'<meta[^>]+name=["\']citation_author_institution["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    ):
        affiliations.append(content.strip())

    return {
        "title": meta.get("citation_title") or meta.get("og:title") or "",
        "abstract": meta.get("citation_abstract") or meta.get("description") or meta.get("og:description") or "",
        "authors": authors,
        "affiliations": list(dict.fromkeys(a for a in affiliations if a)),
        "figure_url": meta.get("og:image", ""),
        "url": meta.get("citation_public_url") or url,
    }


async def search_semantic_scholar_by_title(title: str, sem: asyncio.Semaphore) -> dict:
    query = quote(title)
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={query}"
        "&fields=title,abstract,authors,url,venue,externalIds,openAccessPdf,tldr"
        "&limit=5"
    )
    raw = await curl_fetch(url, sem)
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    for item in payload.get("data", []):
        if not titles_match(title, item.get("title", "")):
            continue
        return {
            "title": item.get("title", ""),
            "abstract": item.get("abstract", "") or "",
            "authors": [a.get("name", "").strip() for a in item.get("authors", []) if isinstance(a, dict) and a.get("name")],
            "url": item.get("url", ""),
            "venue": item.get("venue", ""),
            "external_ids": item.get("externalIds", {}) or {},
            "figure_url": ((item.get("openAccessPdf") or {}).get("url", "")),
            "tldr": ((item.get("tldr") or {}).get("text", "")),
        }
    return {}


async def search_semantic_scholar_by_doi(url_or_doi: str, sem: asyncio.Semaphore) -> dict:
    doi = extract_doi(url_or_doi)
    if not doi:
        return {}

    fields = "title,abstract,authors,url,venue,externalIds,openAccessPdf,tldr"
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{quote(doi, safe='')}"
    url += f"?fields={fields}"
    raw = await curl_fetch(url, sem)
    if not raw:
        return {}

    try:
        item = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    return {
        "title": item.get("title", ""),
        "abstract": item.get("abstract", "") or "",
        "authors": [a.get("name", "").strip() for a in item.get("authors", []) if isinstance(a, dict) and a.get("name")],
        "url": item.get("url", ""),
        "venue": item.get("venue", ""),
        "external_ids": item.get("externalIds", {}) or {},
        "figure_url": ((item.get("openAccessPdf") or {}).get("url", "")),
        "tldr": ((item.get("tldr") or {}).get("text", "")),
    }


def _parse_openalex_work(item: dict) -> dict:
    authors = []
    affiliations = []
    for authorship in item.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        if isinstance(author, dict) and author.get("display_name"):
            authors.append(author["display_name"].strip())
        for institution in authorship.get("institutions") or []:
            if isinstance(institution, dict) and institution.get("display_name"):
                affiliations.append(institution["display_name"].strip())

    doi_value = extract_doi((item.get("doi") or "") or ((item.get("ids") or {}).get("doi") or ""))
    primary_location = item.get("primary_location") or {}
    landing_url = ""
    if isinstance(primary_location, dict):
        landing_url = primary_location.get("landing_page_url", "") or ""

    return {
        "title": item.get("display_name", "") or item.get("title", ""),
        "abstract": reconstruct_openalex_abstract(item.get("abstract_inverted_index") or {}),
        "authors": authors,
        "affiliations": list(dict.fromkeys(a for a in affiliations if a)),
        "url": landing_url or item.get("id", ""),
        "doi": doi_value,
    }


async def search_openalex_by_doi(url_or_doi: str, sem: asyncio.Semaphore) -> dict:
    doi = extract_doi(url_or_doi)
    if not doi:
        return {}

    url = f"https://api.openalex.org/works?filter=doi:{quote(doi, safe='')}&per-page=1"
    raw = await curl_fetch(url, sem)
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    results = payload.get("results") or []
    if not results:
        return {}
    return _parse_openalex_work(results[0])


async def search_openalex_by_title(title: str, sem: asyncio.Semaphore) -> dict:
    url = f"https://api.openalex.org/works?search={quote(title)}&per-page=5"
    raw = await curl_fetch(url, sem)
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    for item in payload.get("results") or []:
        parsed = _parse_openalex_work(item)
        if titles_match(title, parsed.get("title", "")):
            return parsed
    return {}



# ══════════════════════════════════════════════════════════════════════════════
# PDF affiliation extraction
# ══════════════════════════════════════════════════════════════════════════════

EXTRACT_AFFILIATIONS_SCRIPT = str(
    Path(__file__).parent / "extract_affiliations.py"
)
_AFFILIATION_EXTRACTOR = None


def extract_affiliations_from_text(text: str) -> list[str]:
    """Extract affiliation names from text produced by pdftotext."""
    global _AFFILIATION_EXTRACTOR
    if _AFFILIATION_EXTRACTOR is None:
        spec = importlib.util.spec_from_file_location(
            "daily_papers_extract_affiliations",
            EXTRACT_AFFILIATIONS_SCRIPT,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        _AFFILIATION_EXTRACTOR = module.extract_affiliations
    return _AFFILIATION_EXTRACTOR(text)


async def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Convert PDF bytes to text using pdftotext without fetching network data."""
    if not pdf_bytes:
        return ""
    proc = await asyncio.create_subprocess_exec(
        "pdftotext", "-l", "2", "-", "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(
        proc.communicate(input=pdf_bytes),
        timeout=CURL_TIMEOUT + 15,
    )
    return stdout.decode("utf-8", errors="replace") if stdout else ""


async def extract_affiliations_pdf(arxiv_id: str, sem: asyncio.Semaphore,
                                   retries: int = 3) -> list[str]:
    """Extract affiliations from PDF via a mockable PDF fetch layer."""
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    for attempt in range(1, retries + 1):
        try:
            pdf_bytes = await curl_fetch_bytes(pdf_url, sem)
            if not pdf_bytes:
                return []
            text = await extract_text_from_pdf_bytes(pdf_bytes)
            if text:
                affils = extract_affiliations_from_text(text)
                if affils:
                    return affils
        except (asyncio.TimeoutError, Exception) as e:
            print(f"  [pdf] attempt {attempt}/{retries} failed {arxiv_id}: {e}", file=sys.stderr)
        if attempt < retries:
            await asyncio.sleep(3 * attempt)
    return []


# ══════════════════════════════════════════════════════════════════════════════
# Per-paper enrichment
# ══════════════════════════════════════════════════════════════════════════════

async def enrich_one(paper: dict, sem: asyncio.Semaphore) -> dict:
    """Enrich a single paper with metadata from HTML and abs pages."""
    arxiv_id = paper.get("arxiv_id", "")
    if not arxiv_id:
        # Try to extract from URL
        url = paper.get("url", "")
        m = re.search(r"(\d{4}\.\d{4,5})", url)
        arxiv_id = m.group(1) if m else ""
    title = paper.get("title", "")
    result = dict(paper)  # copy
    arxiv_match = {}
    doi_api_metadata = {}
    doi_metadata = {}
    semantic_match = {}
    openalex_match = {}

    try:
        if title and not arxiv_id:
            arxiv_match = await search_arxiv_by_title(title, sem)
            if arxiv_match.get("arxiv_id"):
                arxiv_id = arxiv_match["arxiv_id"]
                result["arxiv_id"] = arxiv_id
                result["url"] = arxiv_match.get("url") or result.get("url", "")
                result["pdf"] = arxiv_match.get("pdf") or result.get("pdf", "")
                result["date"] = arxiv_match.get("date") or result.get("date", "")

        if title:
            if result.get("url") and "doi" in result.get("url", "").lower():
                doi_api_metadata = await fetch_doi_metadata(result["url"], sem)
                semantic_match = await search_semantic_scholar_by_doi(result["url"], sem)
                openalex_match = await search_openalex_by_doi(result["url"], sem)
            if result.get("url") and "doi.org" in result.get("url", ""):
                doi_metadata = await fetch_doi_landing_metadata(result["url"], sem)
            if not semantic_match:
                semantic_match = await search_semantic_scholar_by_title(title, sem)
            if not openalex_match:
                openalex_match = await search_openalex_by_title(title, sem)

        # Fetch HTML page
        html = ""
        if arxiv_id:
            html_url = f"https://arxiv.org/html/{arxiv_id}"
            html = await curl_fetch(html_url, sem)

        # Parse HTML if we got content
        html_authors = []
        html_affiliations = []
        figure_url = ""
        section_headers = []
        captions = []
        has_hardware_eval = False
        has_end_to_end_eval = False
        has_real_workload = False
        method_name = ""
        method_names = []
        method_summary = ""

        if html and ("<html" in html.lower() or len(html) > 200):
            figure_url = extract_figure_url(html, arxiv_id)
            html_authors = extract_authors_html(html)
            html_affiliations = extract_affiliations_html(html)
            section_headers = extract_section_headers(html)
            captions = extract_captions(html)
            has_hardware_eval = extract_has_hardware_eval(html)
            has_end_to_end_eval = extract_has_end_to_end_eval(html)
            has_real_workload = extract_has_real_workload(html)
            method_name = extract_primary_method_name(html, title)
            method_names = extract_method_names(html, title)
            method_summary = extract_method_summary(html)

        # Abs fallback if HTML authors OR affiliations are empty
        abs_authors = []
        abs_affiliations = []
        if arxiv_id and (not html_authors or not html_affiliations):
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            abs_html = await curl_fetch(abs_url, sem)
            if abs_html:
                abs_data = extract_from_abs(abs_html)
                abs_authors = abs_data["authors"]
                abs_affiliations = abs_data["affiliations"]

        # PDF fallback for affiliations if still empty
        pdf_affiliations = []
        if arxiv_id and not html_affiliations and not abs_affiliations:
            pdf_affiliations = await extract_affiliations_pdf(arxiv_id, sem)

        # ── Merge with priority rules ──
        # Principle: new extraction > existing input, but never overwrite non-empty with empty

        # figure_url: HTML curl > keep existing
        result["figure_url"] = (
            figure_url
            or doi_api_metadata.get("figure_url", "")
            or doi_metadata.get("figure_url", "")
            or semantic_match.get("figure_url", "")
            or paper.get("figure_url", "")
        )

        # affiliations: HTML > abs fallback > PDF fallback > arxiv search > OpenAlex > DOI API > DOI landing > keep existing input
        if html_affiliations:
            result["affiliations"] = ", ".join(html_affiliations)
        elif abs_affiliations:
            result["affiliations"] = ", ".join(abs_affiliations)
        elif pdf_affiliations:
            result["affiliations"] = ", ".join(pdf_affiliations)
        elif arxiv_match.get("affiliations"):
            result["affiliations"] = ", ".join(arxiv_match["affiliations"])
        elif openalex_match.get("affiliations"):
            result["affiliations"] = ", ".join(openalex_match["affiliations"])
        elif doi_api_metadata.get("affiliations"):
            result["affiliations"] = ", ".join(doi_api_metadata["affiliations"])
        elif doi_metadata.get("affiliations"):
            result["affiliations"] = ", ".join(doi_metadata["affiliations"])
        # else: keep whatever was in the input (supports re-enriching enriched data)

        # authors: HTML > abs fallback > arxiv search > semantic scholar > OpenAlex > DOI API > DOI landing > keep existing input
        if html_authors:
            result["authors"] = ", ".join(html_authors)
        elif abs_authors:
            result["authors"] = ", ".join(abs_authors)
        elif arxiv_match.get("authors"):
            result["authors"] = ", ".join(arxiv_match["authors"])
        elif semantic_match.get("authors"):
            result["authors"] = ", ".join(semantic_match["authors"])
        elif openalex_match.get("authors"):
            result["authors"] = ", ".join(openalex_match["authors"])
        elif doi_api_metadata.get("authors"):
            result["authors"] = ", ".join(doi_api_metadata["authors"])
        elif doi_metadata.get("authors"):
            result["authors"] = ", ".join(doi_metadata["authors"])
        # else: keep original

        # abstract: keep existing > arxiv search > semantic scholar > OpenAlex > DOI API > DOI landing
        if not result.get("abstract"):
            result["abstract"] = (
                arxiv_match.get("abstract", "")
                or semantic_match.get("abstract", "")
                or openalex_match.get("abstract", "")
                or doi_api_metadata.get("abstract", "")
                or doi_metadata.get("abstract", "")
                or paper.get("abstract", "")
            )

        # Other enriched fields
        result["section_headers"] = section_headers
        result["captions"] = captions
        result["has_hardware_eval"] = has_hardware_eval
        result["has_end_to_end_eval"] = has_end_to_end_eval
        result["has_real_workload"] = has_real_workload
        result["method_name"] = method_name or result.get("method_name", "") or extract_primary_method_name("", title)
        if not method_names and arxiv_match.get("title"):
            method_names = extract_method_names(arxiv_match.get("title", ""), title)
        result["method_names"] = method_names or result.get("method_names", [])
        result["method_summary"] = (
            method_summary
            or semantic_match.get("tldr", "")
            or summarize_abstract(result.get("abstract", ""))
        )

        result["doi"] = (
            doi_api_metadata.get("doi", "")
            or openalex_match.get("doi", "")
            or semantic_match.get("external_ids", {}).get("DOI", "")
            or result.get("doi", "")
        )

    except Exception as e:
        print(f"  [error] {arxiv_id}: {e}", file=sys.stderr)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

async def enrich_all(papers: list[dict]) -> list[dict]:
    """Enrich all papers concurrently with a semaphore limit."""
    sem = asyncio.Semaphore(SEMAPHORE_LIMIT)
    tasks = [asyncio.create_task(enrich_one(paper, sem)) for paper in papers]

    # gather preserves order and handles exceptions inline
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    ordered = []
    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            print(f"  [error] paper #{i} ({papers[i].get('arxiv_id','')}): {result}", file=sys.stderr)
            ordered.append(papers[i])
        else:
            ordered.append(result)

    return ordered


def main():
    # Optional: output file path as first argument (more robust than stdout redirect)
    output_path = sys.argv[1] if len(sys.argv) > 1 else None

    input_data = sys.stdin.read()
    if not input_data.strip():
        _write_output("[]", output_path)
        return

    try:
        papers = json.loads(input_data)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}", file=sys.stderr)
        _write_output("[]", output_path)
        sys.exit(1)

    if not papers:
        _write_output("[]", output_path)
        return

    print(f"Enriching {len(papers)} papers...", file=sys.stderr)
    enriched = asyncio.run(enrich_all(papers))
    print(f"Done. Enriched {len(enriched)} papers.", file=sys.stderr)

    output = json.dumps(enriched, ensure_ascii=False, indent=2) + "\n"
    _write_output(output, output_path)


def _write_output(data: str, output_path: str | None):
    """Write output to file (if path given) or stdout with explicit flush."""
    if output_path:
        with open(output_path, "w") as f:
            f.write(data)
    else:
        sys.stdout.write(data)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
