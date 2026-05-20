#!/usr/bin/env python3
"""
Zotero 数据库查询辅助脚本
用于 paper-reader skill 的 Zotero 集成
"""

import sqlite3
import os
import shutil
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

_SHARED_DIR = Path(__file__).resolve().parents[2] / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from user_config import paper_notes_dir, zotero_db_path, zotero_storage_dir

# 默认配置
ZOTERO_DB = zotero_db_path()
STORAGE_DIR = zotero_storage_dir()
ZOTERO_DIR = ZOTERO_DB.parent

DEPRECATED_COMMAND_REPLACEMENTS = {
    "papers": "zotero_helper.py resolve --collection-id <collection_id> [--recursive]",
    "search": 'zotero_helper.py resolve --query "<keyword>"',
    "info": "zotero_helper.py resolve --item-id <item_id>",
    "find-collection": 'zotero_helper.py resolve --collection "<collection name or path>"',
}


class CopiedZoteroConnection(sqlite3.Connection):
    """sqlite3 connection carrying the temporary copy path for cleanup."""

    temp_copy_path: Path


def copy_db(db_path: Path = ZOTERO_DB) -> CopiedZoteroConnection:
    """复制数据库以避免锁定"""
    fd, temp_name = tempfile.mkstemp(prefix="zotero_readonly_", suffix=".sqlite")
    os.close(fd)
    temp_path = Path(temp_name)
    shutil.copy2(Path(db_path), temp_path)
    conn = sqlite3.connect(temp_path, factory=CopiedZoteroConnection)
    conn.temp_copy_path = temp_path
    conn.execute("PRAGMA query_only = ON")
    return conn


def close_copied_db(conn: sqlite3.Connection):
    """关闭 copy_db 创建的连接，并删除独立临时库。"""
    temp_path = getattr(conn, "temp_copy_path", None)
    conn.close()
    if temp_path:
        Path(temp_path).unlink(missing_ok=True)


def get_all_child_collections(conn, collection_id: int) -> list[int]:
    """递归获取所有子分类ID（包含自身）"""
    cursor = conn.cursor()
    cursor.execute("SELECT collectionID, parentCollectionID FROM collections")
    all_collections = cursor.fetchall()

    # 构建父子关系映射
    children_map = {}
    for cid, parent_id in all_collections:
        if parent_id not in children_map:
            children_map[parent_id] = []
        children_map[parent_id].append(cid)

    # 递归收集所有子分类
    result = [collection_id]
    def collect_children(cid):
        if cid in children_map:
            for child_id in children_map[cid]:
                result.append(child_id)
                collect_children(child_id)

    collect_children(collection_id)
    return result


def load_collections(conn) -> dict[int, dict[str, Any]]:
    """读取 Zotero collection 元数据。"""
    cursor = conn.cursor()
    cursor.execute("SELECT collectionID, collectionName, parentCollectionID FROM collections")
    return {
        row[0]: {"collection_id": row[0], "name": row[1], "parent": row[2]}
        for row in cursor.fetchall()
    }


def collection_path_from_map(collections: dict[int, dict[str, Any]], collection_id: int) -> str:
    path_parts = []
    current = collection_id
    seen = set()

    while current and current not in seen:
        seen.add(current)
        info = collections.get(current)
        if not info:
            break
        path_parts.insert(0, info["name"])
        current = info["parent"]

    return "/".join(path_parts)


def collection_depth(collections: dict[int, dict[str, Any]], collection_id: int) -> int:
    path = collection_path_from_map(collections, collection_id)
    return len([part for part in path.split("/") if part])


def build_collection_record(conn, collection_id: int) -> dict[str, Any]:
    collections = load_collections(conn)
    info = collections[collection_id]
    return {
        "collection_id": collection_id,
        "name": info["name"],
        "parent_collection_id": info["parent"],
        "path": collection_path_from_map(collections, collection_id),
    }


def find_collections(conn, collection_ref: str) -> list[dict[str, Any]]:
    """按 ID、完整路径、末级名称或模糊路径查找 collection。"""
    ref = str(collection_ref).strip()
    if not ref:
        return []

    collections = load_collections(conn)
    records = []
    for cid, info in collections.items():
        path = collection_path_from_map(collections, cid)
        records.append(
            {
                "collection_id": cid,
                "name": info["name"],
                "parent_collection_id": info["parent"],
                "path": path,
            }
        )

    if ref.isdigit():
        cid = int(ref)
        return [record for record in records if record["collection_id"] == cid]

    ref_lower = ref.lower()
    exact = [
        record
        for record in records
        if record["path"].lower() == ref_lower or record["name"].lower() == ref_lower
    ]
    if exact:
        return sorted(exact, key=lambda record: record["path"])

    return sorted(
        [
            record
            for record in records
            if ref_lower in record["path"].lower() or ref_lower in record["name"].lower()
        ],
        key=lambda record: record["path"],
    )


def get_item_key(conn, item_id: int) -> Optional[str]:
    cursor = conn.cursor()
    cursor.execute("SELECT key FROM items WHERE itemID = ?", (item_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def get_item_fields(conn, item_id: int) -> dict[str, str]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT f.fieldName, idv.value
        FROM itemData id
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        JOIN fields f ON id.fieldID = f.fieldID
        WHERE id.itemID = ?
        """,
        (item_id,),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def field_value(fields: dict[str, str], *names: str) -> str:
    by_lower = {key.lower(): value for key, value in fields.items()}
    for name in names:
        value = fields.get(name)
        if value:
            return value
        value = by_lower.get(name.lower())
        if value:
            return value
    return ""


def extract_year(date_value: str) -> str:
    match = re.search(r"(?:19|20)\d{2}", date_value or "")
    return match.group(0) if match else ""


def extract_arxiv_id(fields: dict[str, str]) -> str:
    candidates = [
        field_value(fields, "archiveID"),
        field_value(fields, "extra"),
        field_value(fields, "url"),
    ]
    patterns = [
        r"arXiv[:\s]+([a-z-]+/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)",
        r"arxiv\.org/(?:abs|pdf)/([a-z-]+/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        for pattern in patterns:
            match = re.search(pattern, candidate, re.IGNORECASE)
            if match:
                return match.group(1)
    return ""


def get_item_authors(conn, item_id: int) -> list[str]:
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT cd.firstName, cd.lastName, cd.shortName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorData cd ON c.creatorDataID = cd.creatorDataID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """,
            (item_id,),
        )
    except sqlite3.OperationalError:
        return []

    authors = []
    for first_name, last_name, short_name in cursor.fetchall():
        if short_name:
            authors.append(short_name)
            continue
        name = " ".join(part for part in [first_name, last_name] if part)
        if name:
            authors.append(name)
    return authors


def resolve_pdf_path(conn, item_id: int, storage_dir: Path = STORAGE_DIR) -> Optional[str]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ia.path, items.key
        FROM itemAttachments ia
        JOIN items ON ia.itemID = items.itemID
        WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf'
        ORDER BY ia.itemID
        LIMIT 1
        """,
        (item_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    attachment_path, attachment_key = row
    if not attachment_path:
        return None
    if attachment_path.startswith("storage:"):
        filename = attachment_path.replace("storage:", "", 1)
        return str(Path(storage_dir) / attachment_key / filename)
    return str(Path(attachment_path).expanduser())


def get_item_collection_records(conn, item_id: int) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.collectionID, c.collectionName
        FROM collections c
        JOIN collectionItems ci ON c.collectionID = ci.collectionID
        WHERE ci.itemID = ?
        """,
        (item_id,),
    )
    collections = load_collections(conn)
    records = []
    for collection_id, name in cursor.fetchall():
        records.append(
            {
                "collection_id": collection_id,
                "name": name,
                "path": collection_path_from_map(collections, collection_id),
            }
        )
    return sorted(records, key=lambda record: record["path"])


def build_item_record(
    conn,
    item_id: int,
    *,
    source_collection_id: Optional[int] = None,
    storage_dir: Path = STORAGE_DIR,
) -> dict[str, Any]:
    """返回 paper-reader 可直接消费的 Zotero item 结构化信息。"""
    fields = get_item_fields(conn, item_id)
    date = field_value(fields, "date")
    collections = get_item_collection_records(conn, item_id)
    source_collection_path = None
    if source_collection_id is not None:
        source_collection_path = get_collection_path(conn, source_collection_id)

    return {
        "item_id": item_id,
        "item_key": get_item_key(conn, item_id),
        "title": field_value(fields, "title") or "Unknown",
        "authors": get_item_authors(conn, item_id),
        "date": date,
        "year": extract_year(date),
        "venue": field_value(
            fields,
            "publicationTitle",
            "conferenceName",
            "proceedingsTitle",
            "journalAbbreviation",
            "meetingName",
        ),
        "url": field_value(fields, "url"),
        "doi": field_value(fields, "DOI", "doi"),
        "arxiv_id": extract_arxiv_id(fields),
        "pdf_path": resolve_pdf_path(conn, item_id, storage_dir=storage_dir),
        "collections": collections,
        "collection_paths": [record["path"] for record in collections],
        "source_collection_path": source_collection_path,
    }


def search_item_records(
    conn,
    keyword: str,
    *,
    limit: int = 20,
    storage_dir: Path = STORAGE_DIR,
) -> list[dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT i.itemID,
               (SELECT value FROM itemData id2
                JOIN itemDataValues idv2 ON id2.valueID = idv2.valueID
                JOIN fields f2 ON id2.fieldID = f2.fieldID
                WHERE id2.itemID = i.itemID AND f2.fieldName = 'date' LIMIT 1) as date
        FROM items i
        JOIN itemData id ON i.itemID = id.itemID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        JOIN fields f ON id.fieldID = f.fieldID
        WHERE f.fieldName = 'title'
          AND i.itemTypeID != 14
          AND idv.value LIKE ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (f"%{keyword}%", limit),
    )
    return [
        build_item_record(conn, row[0], storage_dir=storage_dir)
        for row in cursor.fetchall()
    ]


def choose_most_specific_collection(
    collections: dict[int, dict[str, Any]],
    collection_ids: list[int],
) -> int:
    return sorted(
        collection_ids,
        key=lambda cid: (
            -collection_depth(collections, cid),
            collection_path_from_map(collections, cid),
        ),
    )[0]


def resolve_items_for_collection(
    conn,
    collection_id: int,
    *,
    recursive: bool = False,
    storage_dir: Path = STORAGE_DIR,
) -> list[dict[str, Any]]:
    """解析 collection 下的论文；递归时记录 item 所属 subtree 中最具体的来源路径。"""
    collection_ids = get_all_child_collections(conn, collection_id) if recursive else [collection_id]
    placeholders = ",".join("?" * len(collection_ids))
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT i.itemID, ci.collectionID
        FROM items i
        JOIN collectionItems ci ON i.itemID = ci.itemID
        WHERE ci.collectionID IN ({placeholders})
          AND i.itemTypeID != 14
        ORDER BY i.itemID
        """,
        collection_ids,
    )

    source_candidates: dict[int, list[int]] = {}
    for item_id, source_collection_id in cursor.fetchall():
        source_candidates.setdefault(item_id, []).append(source_collection_id)

    collections = load_collections(conn)
    records = []
    for item_id, candidate_ids in source_candidates.items():
        source_collection_id = choose_most_specific_collection(collections, candidate_ids)
        records.append(
            build_item_record(
                conn,
                item_id,
                source_collection_id=source_collection_id,
                storage_dir=storage_dir,
            )
        )

    return sorted(records, key=lambda record: (record.get("date") or "", record["title"]), reverse=True)


_UNSAFE_PATH_CHARS = re.compile(r'[<>:"\\|?*\x00-\x1f]')
_UNSAFE_FILENAME_CHARS = re.compile(r'[/<>:"\\|?*\x00-\x1f]')


def sanitize_path_segment(segment: str) -> str:
    cleaned = _UNSAFE_PATH_CHARS.sub("_", str(segment)).strip().rstrip(".")
    return cleaned or "_untitled"


def sanitize_filename(stem: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", str(stem)).strip().rstrip(".")
    return cleaned or "Untitled"


def sanitize_collection_path(collection_path: str) -> str:
    return "/".join(
        sanitize_path_segment(part)
        for part in str(collection_path).split("/")
        if part
    )


def normalize_lookup_key(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", normalized)


def normalize_doi(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    raw = re.sub(r"^doi:\s*", "", raw)
    raw = raw.replace("https://doi.org/", "").replace("http://doi.org/", "")
    raw = raw.replace("https://dx.doi.org/", "").replace("http://dx.doi.org/", "")
    return raw.strip().rstrip(".")


def normalize_arxiv_id(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", raw, re.IGNORECASE)
    return match.group(1) if match else raw.lower().removeprefix("arxiv:").strip()


def normalize_year(value: Optional[Any]) -> str:
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return match.group(0) if match else ""


def title_lookup_keys(value: Optional[str]) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    keys = {normalize_lookup_key(text)}
    if ":" in text:
        keys.add(normalize_lookup_key(text.split(":", 1)[0]))
    return {key for key in keys if key}


def infer_method_name(title: str) -> str:
    text = str(title or "").strip().rstrip(".")
    if not text:
        return "Untitled"
    if ":" in text:
        prefix = text.split(":", 1)[0].strip()
        generic_prefixes = ("towards ", "toward ", "understanding ", "analyzing ", "optimizing ")
        if 1 < len(prefix) <= 40 and not prefix.lower().startswith(generic_prefixes):
            return prefix
    return text


def build_note_path(paper_notes_root: Path, collection_path: str, method_name: str) -> Path:
    root = Path(paper_notes_root)
    sanitized_collection_path = sanitize_collection_path(collection_path)
    if sanitized_collection_path:
        target_dir = root
        for part in sanitized_collection_path.split("/"):
            target_dir = target_dir / part
    else:
        target_dir = root / "_inbox"
    return target_dir / f"{sanitize_filename(method_name)}.md"


class NoteRecord:
    def __init__(
        self,
        path: Path,
        frontmatter: dict[str, Any],
        *,
        title: str = "",
        method_name: str = "",
        year: str = "",
        venue: str = "",
        authors: Optional[list[str]] = None,
    ):
        self.path = Path(path)
        self.frontmatter = frontmatter
        self.title = title
        self.method_name = method_name
        self.year = year
        self.venue = venue
        self.authors = authors or []

    @property
    def first_author_key(self) -> str:
        return normalize_lookup_key(self.authors[0]) if self.authors else ""


class NoteMatch:
    def __init__(self, record: NoteRecord, match_level: str, confidence: str, *, conflict: bool = False):
        self.record = record
        self.path = record.path
        self.match_level = match_level
        self.confidence = confidence
        self.conflict = conflict

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "match_level": self.match_level,
            "confidence": self.confidence,
            "conflict": self.conflict,
        }


class NoteIndex:
    def __init__(self):
        self.records: list[NoteRecord] = []
        self.by_zotero_id: dict[int, list[NoteRecord]] = {}
        self.by_doi: dict[str, list[NoteRecord]] = {}
        self.by_arxiv_id: dict[str, list[NoteRecord]] = {}
        self.by_norm_title: dict[str, list[NoteRecord]] = {}
        self.by_norm_method: dict[str, list[NoteRecord]] = {}

    @staticmethod
    def _add(mapping: dict[Any, list[NoteRecord]], key: Any, record: NoteRecord):
        if key:
            mapping.setdefault(key, []).append(record)

    def add(self, record: NoteRecord):
        self.records.append(record)

        zotero_id = record.frontmatter.get("zotero_item_id")
        try:
            if zotero_id not in (None, ""):
                self._add(self.by_zotero_id, int(zotero_id), record)
        except (TypeError, ValueError):
            pass

        self._add(self.by_doi, normalize_doi(record.frontmatter.get("doi")), record)
        self._add(self.by_arxiv_id, normalize_arxiv_id(record.frontmatter.get("arxiv_id")), record)

        for key in title_lookup_keys(record.title):
            self._add(self.by_norm_title, key, record)
        for key in title_lookup_keys(record.path.stem):
            self._add(self.by_norm_title, key, record)

        for key in {normalize_lookup_key(record.method_name), normalize_lookup_key(record.path.stem)}:
            self._add(self.by_norm_method, key, record)


def parse_frontmatter_scalar(raw_value: str) -> Any:
    value = str(raw_value).strip()
    if "  #" in value:
        value = value.split("  #", 1)[0].strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_frontmatter_scalar(part) for part in inner.split(",")]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    return value


def parse_note_frontmatter(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}

    if not lines or lines[0].strip() != "---":
        return {}

    data: dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped or stripped.startswith("#"):
            continue
        if current_list_key and stripped.startswith("- "):
            data.setdefault(current_list_key, []).append(parse_frontmatter_scalar(stripped[2:]))
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value == "":
            data[key] = []
            current_list_key = key
        else:
            data[key] = parse_frontmatter_scalar(value)

    return data


def _frontmatter_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(";") if part.strip()]
    return []


def should_index_note(path: Path, paper_notes_root: Path) -> bool:
    if path.suffix != ".md":
        return False
    try:
        relative_parts = path.relative_to(paper_notes_root).parts
    except ValueError:
        return False
    if "_concepts" in relative_parts:
        return False
    if path.stem.startswith("_index_"):
        return False
    return True


def build_note_index(paper_notes_root: Path) -> NoteIndex:
    root = Path(paper_notes_root)
    index = NoteIndex()
    if not root.exists():
        return index
    for path in sorted(root.rglob("*.md")):
        if not should_index_note(path, root):
            continue
        frontmatter = parse_note_frontmatter(path)
        record = NoteRecord(
            path,
            frontmatter,
            title=str(frontmatter.get("title") or ""),
            method_name=str(frontmatter.get("method_name") or ""),
            year=normalize_year(frontmatter.get("year")),
            venue=str(frontmatter.get("venue") or ""),
            authors=_frontmatter_list(frontmatter.get("authors")),
        )
        index.add(record)
    return index


def _unique_records(records: list[NoteRecord]) -> list[NoteRecord]:
    unique: dict[Path, NoteRecord] = {}
    for record in records:
        unique.setdefault(record.path, record)
    return list(unique.values())


def _record_matches_weak_metadata(
    record: NoteRecord,
    *,
    year: Optional[Any] = None,
    venue: Optional[str] = None,
    authors: Optional[list[str]] = None,
) -> tuple[bool, str]:
    checks = []
    wanted_year = normalize_year(year)
    if wanted_year:
        if not record.year:
            return False, "low"
        checks.append(record.year == wanted_year)

    wanted_venue = normalize_lookup_key(venue or "")
    if wanted_venue:
        if not record.venue:
            return False, "low"
        checks.append(normalize_lookup_key(record.venue) == wanted_venue)

    wanted_first_author = normalize_lookup_key(authors[0]) if authors else ""
    if wanted_first_author:
        if not record.first_author_key:
            return False, "low"
        checks.append(record.first_author_key == wanted_first_author)

    if not checks:
        return True, "low"
    return all(checks), "high" if all(checks) else "low"


def _matches(records: list[NoteRecord], match_level: str, confidence: str, *, conflict: bool = False) -> list[NoteMatch]:
    return [NoteMatch(record, match_level, confidence, conflict=conflict) for record in _unique_records(records)]


def find_matching_notes(
    paper_notes_root: Path,
    *,
    zotero_item_id: Optional[int] = None,
    doi: Optional[str] = None,
    arxiv_id: Optional[str] = None,
    title: Optional[str] = None,
    method_name: Optional[str] = None,
    year: Optional[Any] = None,
    venue: Optional[str] = None,
    authors: Optional[list[str]] = None,
    index: Optional[NoteIndex] = None,
) -> list[NoteMatch]:
    note_index = index or build_note_index(paper_notes_root)

    if zotero_item_id not in (None, ""):
        try:
            records = note_index.by_zotero_id.get(int(zotero_item_id), [])
        except (TypeError, ValueError):
            records = []
        if records:
            conflict = len(_unique_records(records)) > 1
            return _matches(records, "zotero_item_id", "exact", conflict=conflict)

    doi_key = normalize_doi(doi)
    if doi_key and note_index.by_doi.get(doi_key):
        return _matches(note_index.by_doi[doi_key], "doi", "exact")

    arxiv_key = normalize_arxiv_id(arxiv_id)
    if arxiv_key and note_index.by_arxiv_id.get(arxiv_key):
        return _matches(note_index.by_arxiv_id[arxiv_key], "arxiv_id", "exact")

    title_records: list[NoteRecord] = []
    for key in title_lookup_keys(title):
        title_records.extend(note_index.by_norm_title.get(key, []))
    if title_records:
        return _matches(title_records, "title", "high")

    method_key = normalize_lookup_key(method_name or "")
    method_records = note_index.by_norm_method.get(method_key, []) if method_key else []
    filtered_records = []
    confidence = "low"
    for record in method_records:
        ok, record_confidence = _record_matches_weak_metadata(record, year=year, venue=venue, authors=authors)
        if ok:
            filtered_records.append(record)
            if record_confidence == "high":
                confidence = "high"
    if filtered_records:
        return _matches(filtered_records, "method_name", confidence)

    return []


def find_existing_note_paths(paper_notes_root: Path, method_name: str) -> list[Path]:
    root = Path(paper_notes_root)
    if not root.exists():
        return []
    filename = f"{sanitize_filename(method_name)}.md"
    return sorted(path for path in root.rglob(filename) if path.is_file())


def plan_note_save(
    paper_notes_root: Path,
    method_name: str,
    collection_path: str,
    *,
    existing_paths: Optional[list[Path]] = None,
    batch: bool = False,
    zotero_item_id: Optional[int] = None,
    doi: Optional[str] = None,
    arxiv_id: Optional[str] = None,
    title: Optional[str] = None,
    matches: Optional[list[NoteMatch]] = None,
) -> dict[str, Any]:
    target_path = build_note_path(paper_notes_root, collection_path, method_name)
    sanitized_collection_path = sanitize_collection_path(collection_path)
    frontmatter_updates: dict[str, Any] = {"zotero_collection": sanitized_collection_path or "_inbox"}
    if zotero_item_id is not None:
        frontmatter_updates["zotero_item_id"] = zotero_item_id
    if doi:
        frontmatter_updates["doi"] = normalize_doi(doi)
    if arxiv_id:
        frontmatter_updates["arxiv_id"] = normalize_arxiv_id(arxiv_id)
    if title:
        frontmatter_updates["title"] = title

    candidate_matches = matches
    if candidate_matches is None and existing_paths is None:
        candidate_matches = find_matching_notes(
            paper_notes_root,
            zotero_item_id=zotero_item_id,
            doi=doi,
            arxiv_id=arxiv_id,
            title=title,
            method_name=method_name,
        )

    if candidate_matches:
        candidate_paths = [match.path for match in candidate_matches]
        if any(match.conflict for match in candidate_matches):
            return {
                "action": "conflict",
                "target_path": str(target_path),
                "existing_path": str(candidate_paths[0]),
                "candidate_paths": [str(path) for path in candidate_paths],
                "frontmatter_updates": frontmatter_updates,
                "match": candidate_matches[0].to_dict(),
            }

        best = candidate_matches[0]
        if best.match_level == "method_name" and best.confidence != "high":
            return {
                "action": "create",
                "target_path": str(target_path),
                "existing_path": None,
                "candidate_paths": [str(path) for path in candidate_paths],
                "frontmatter_updates": frontmatter_updates,
                "match": best.to_dict(),
            }

        existing_path = best.path
        if existing_path == target_path:
            action = "skip" if batch else "update"
        else:
            action = "skip" if batch else "move"
        return {
            "action": action,
            "target_path": str(target_path),
            "existing_path": str(existing_path),
            "candidate_paths": [str(path) for path in candidate_paths],
            "frontmatter_updates": frontmatter_updates,
            "match": best.to_dict(),
        }

    existing = [Path(path) for path in (existing_paths if existing_paths is not None else find_existing_note_paths(paper_notes_root, method_name))]
    matching_elsewhere = [path for path in existing if path != target_path]

    if batch and (existing or target_path.exists()):
        action = "skip"
        existing_path = target_path if target_path in existing or target_path.exists() else existing[0]
    elif target_path in existing or target_path.exists():
        action = "skip" if batch else "update"
        existing_path = target_path
    elif matching_elsewhere:
        action = "move"
        existing_path = matching_elsewhere[0]
    else:
        action = "create"
        existing_path = None

    return {
        "action": action,
        "target_path": str(target_path),
        "existing_path": str(existing_path) if existing_path else None,
        "candidate_paths": [],
        "frontmatter_updates": frontmatter_updates,
    }


def print_json(data: Any):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def warn_if_deprecated_command(command: str) -> None:
    replacement = DEPRECATED_COMMAND_REPLACEMENTS.get(command)
    if not replacement:
        return
    print(
        f"[DEPRECATED] zotero_helper.py {command} is deprecated; use {replacement}. "
        "This compatibility command will be removed in the next related zotero_helper cleanup.",
        file=sys.stderr,
    )


def list_collections(conn):
    """列出所有分类"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.collectionID, c.collectionName, c.parentCollectionID,
               COUNT(ci.itemID) as item_count
        FROM collections c
        LEFT JOIN collectionItems ci ON c.collectionID = ci.collectionID
        GROUP BY c.collectionID
        ORDER BY c.parentCollectionID NULLS FIRST, c.collectionName
    """)

    print("ID\t| 分类名称\t\t\t| 父分类\t| 文献数")
    print("-" * 70)
    for row in cursor.fetchall():
        parent = str(row[2]) if row[2] else "根目录"
        name = row[1][:24] if row[1] else ""
        print(f"{row[0]}\t| {name:24}\t| {parent:8}\t| {row[3]}")


def list_papers_in_collection(conn, collection_id, recursive=False):
    """列出分类下的论文（支持递归子分类）"""
    cursor = conn.cursor()

    if recursive:
        collection_ids = get_all_child_collections(conn, collection_id)
        placeholders = ','.join('?' * len(collection_ids))
        query = f"""
            SELECT DISTINCT i.itemID, idv.value as title,
                   (SELECT value FROM itemData id2
                    JOIN itemDataValues idv2 ON id2.valueID = idv2.valueID
                    JOIN fields f2 ON id2.fieldID = f2.fieldID
                    WHERE id2.itemID = i.itemID AND f2.fieldName = 'date' LIMIT 1) as date
            FROM items i
            JOIN collectionItems ci ON i.itemID = ci.itemID
            JOIN itemData id ON i.itemID = id.itemID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            JOIN fields f ON id.fieldID = f.fieldID
            WHERE ci.collectionID IN ({placeholders})
              AND f.fieldName = 'title'
              AND i.itemTypeID != 14
            ORDER BY date DESC
        """
        cursor.execute(query, collection_ids)
        print(f"(递归查询，包含 {len(collection_ids)} 个分类)")
    else:
        cursor.execute("""
            SELECT i.itemID, idv.value as title,
                   (SELECT value FROM itemData id2
                    JOIN itemDataValues idv2 ON id2.valueID = idv2.valueID
                    JOIN fields f2 ON id2.fieldID = f2.fieldID
                    WHERE id2.itemID = i.itemID AND f2.fieldName = 'date' LIMIT 1) as date
            FROM items i
            JOIN collectionItems ci ON i.itemID = ci.itemID
            JOIN itemData id ON i.itemID = id.itemID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            JOIN fields f ON id.fieldID = f.fieldID
            WHERE ci.collectionID = ?
              AND f.fieldName = 'title'
              AND i.itemTypeID != 14
            ORDER BY date DESC
        """, (collection_id,))

    print("ItemID\t| 日期\t\t| 标题")
    print("-" * 80)
    for row in cursor.fetchall():
        title = row[1][:50] if row[1] else ""
        date = row[2][:10] if row[2] else "N/A"
        print(f"{row[0]}\t| {date}\t| {title}")


def search_paper(conn, keyword):
    """搜索论文标题"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.itemID, idv.value as title,
               (SELECT value FROM itemData id2
                JOIN itemDataValues idv2 ON id2.valueID = idv2.valueID
                JOIN fields f2 ON id2.fieldID = f2.fieldID
                WHERE id2.itemID = i.itemID AND f2.fieldName = 'date' LIMIT 1) as date
        FROM items i
        JOIN itemData id ON i.itemID = id.itemID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        JOIN fields f ON id.fieldID = f.fieldID
        WHERE f.fieldName = 'title'
          AND i.itemTypeID != 14
          AND idv.value LIKE ?
        ORDER BY date DESC
        LIMIT 20
    """, (f"%{keyword}%",))

    print(f"搜索: '{keyword}'")
    print("ItemID\t| 日期\t\t| 标题")
    print("-" * 80)
    for row in cursor.fetchall():
        title = row[1][:50] if row[1] else ""
        date = row[2][:10] if row[2] else "N/A"
        print(f"{row[0]}\t| {date}\t| {title}")


def get_pdf_path(conn, item_id):
    """获取论文 PDF 路径"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ia.path, items.key,
               (SELECT value FROM itemData id
                JOIN itemDataValues idv ON id.valueID = idv.valueID
                JOIN fields f ON id.fieldID = f.fieldID
                WHERE id.itemID = ia.parentItemID AND f.fieldName = 'title') as title
        FROM itemAttachments ia
        JOIN items ON ia.itemID = items.itemID
        WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf'
    """, (item_id,))

    row = cursor.fetchone()
    if row:
        path, key, title = row
        if path and path.startswith('storage:'):
            filename = path.replace('storage:', '')
            full_path = STORAGE_DIR / key / filename
            print(f"标题: {title}")
            print(f"PDF路径: {full_path}")
            if full_path.exists():
                print(f"文件存在: Yes")
                return str(full_path)
            else:
                print(f"文件存在: No")
    else:
        print(f"未找到 itemID={item_id} 的 PDF 附件")
    return None


def get_collection_path(conn, collection_id):
    """获取分类的完整路径"""
    cursor = conn.cursor()
    cursor.execute("SELECT collectionID, collectionName, parentCollectionID FROM collections")
    collections = {row[0]: {'name': row[1], 'parent': row[2]} for row in cursor.fetchall()}

    path_parts = []
    current = collection_id
    while current:
        if current in collections:
            path_parts.insert(0, collections[current]['name'])
            current = collections[current]['parent']
        else:
            break
    return '/'.join(path_parts)


def get_item_collections(conn, item_id):
    """获取论文所在的所有分类"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.collectionID, c.collectionName
        FROM collections c
        JOIN collectionItems ci ON c.collectionID = ci.collectionID
        WHERE ci.itemID = ?
    """, (item_id,))
    return cursor.fetchall()


def add_to_collection_db(item_id, collection_id):
    """将论文添加到分类（需要直接操作原数据库）"""
    # 注意：这会直接修改 Zotero 数据库，需谨慎
    conn = sqlite3.connect(ZOTERO_DB)
    cursor = conn.cursor()
    try:
        # 检查是否已存在
        cursor.execute("""
            SELECT 1 FROM collectionItems
            WHERE collectionID = ? AND itemID = ?
        """, (collection_id, item_id))
        if cursor.fetchone():
            print(f"论文 {item_id} 已在分类 {collection_id} 中")
            return False

        # 添加到分类
        cursor.execute("""
            INSERT INTO collectionItems (collectionID, itemID, orderIndex)
            VALUES (?, ?, 0)
        """, (collection_id, item_id))
        conn.commit()
        print(f"已将论文 {item_id} 添加到分类 {collection_id}")
        return True
    except Exception as e:
        print(f"添加失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def remove_from_collection_db(item_id, collection_id):
    """从分类中移除论文"""
    conn = sqlite3.connect(ZOTERO_DB)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            DELETE FROM collectionItems
            WHERE collectionID = ? AND itemID = ?
        """, (collection_id, item_id))
        if cursor.rowcount > 0:
            conn.commit()
            print(f"已从分类 {collection_id} 移除论文 {item_id}")
            return True
        else:
            print(f"论文 {item_id} 不在分类 {collection_id} 中")
            return False
    except Exception as e:
        print(f"移除失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def move_to_collection(item_id, new_collection_id, old_collection_id=None):
    """移动论文到新分类（先添加到新分类，再从旧分类移除）"""
    # 先添加到新分类
    add_to_collection_db(item_id, new_collection_id)

    # 如果指定了旧分类，从旧分类移除
    if old_collection_id:
        remove_from_collection_db(item_id, old_collection_id)


def find_collection_by_name(conn, name):
    """根据名称查找分类"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT collectionID, collectionName, parentCollectionID
        FROM collections
        WHERE collectionName LIKE ?
    """, (f"%{name}%",))
    results = cursor.fetchall()
    for r in results:
        path = get_collection_path(conn, r[0])
        print(f"ID: {r[0]}, 路径: {path}")
    return results


def get_paper_info(conn, item_id):
    """获取论文详细信息"""
    cursor = conn.cursor()

    # 获取标题
    cursor.execute("""
        SELECT idv.value
        FROM itemData id
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        JOIN fields f ON id.fieldID = f.fieldID
        WHERE id.itemID = ? AND f.fieldName = 'title'
    """, (item_id,))
    title_row = cursor.fetchone()
    title = title_row[0] if title_row else "Unknown"

    # 获取其他字段
    cursor.execute("""
        SELECT f.fieldName, idv.value
        FROM itemData id
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        JOIN fields f ON id.fieldID = f.fieldID
        WHERE id.itemID = ?
    """, (item_id,))
    fields = {row[0]: row[1] for row in cursor.fetchall()}

    # 获取所在分类
    collections = get_item_collections(conn, item_id)
    collection_paths = [get_collection_path(conn, c[0]) for c in collections]

    print(f"ItemID: {item_id}")
    print(f"标题: {title}")
    print(f"日期: {fields.get('date', 'N/A')}")
    print(f"URL: {fields.get('url', 'N/A')}")
    print(f"所在分类: {', '.join(collection_paths) if collection_paths else '无'}")

    return {
        'item_id': item_id,
        'title': title,
        'fields': fields,
        'collections': collections,
        'collection_paths': collection_paths
    }


def main():
    parser = argparse.ArgumentParser(description='Zotero 数据库查询工具')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # 列出分类
    subparsers.add_parser('collections', help='列出所有分类')

    # 列出分类下的论文
    papers_parser = subparsers.add_parser('papers', help='列出分类下的论文')
    papers_parser.add_argument('collection_id', type=int, help='分类ID')
    papers_parser.add_argument('--recursive', '-r', action='store_true', help='递归包含子分类')

    # 搜索论文
    search_parser = subparsers.add_parser('search', help='搜索论文')
    search_parser.add_argument('keyword', help='搜索关键词')

    # 获取 PDF 路径
    pdf_parser = subparsers.add_parser('pdf', help='获取 PDF 路径')
    pdf_parser.add_argument('item_id', type=int, help='论文 ItemID')

    # 获取论文信息
    info_parser = subparsers.add_parser('info', help='获取论文详细信息')
    info_parser.add_argument('item_id', type=int, help='论文 ItemID')

    # 查找分类
    find_parser = subparsers.add_parser('find-collection', help='根据名称查找分类')
    find_parser.add_argument('name', help='分类名称（支持模糊匹配）')

    # 统一解析入口：按 query / item_id / collection 返回结构化 JSON
    resolve_parser = subparsers.add_parser('resolve', help='解析 Zotero item/search/collection 为结构化 JSON')
    resolve_group = resolve_parser.add_mutually_exclusive_group(required=True)
    resolve_group.add_argument('--query', help='按标题关键词搜索论文')
    resolve_group.add_argument('--item-id', type=int, help='按 Zotero itemID 获取论文')
    resolve_group.add_argument('--collection', help='按 collection 名称或路径获取论文')
    resolve_group.add_argument('--collection-id', type=int, help='按 collection ID 获取论文')
    resolve_parser.add_argument('--recursive', '-r', action='store_true', help='collection 查询递归包含子分类')
    resolve_parser.add_argument('--limit', type=int, default=20, help='query 最多返回条目数')

    note_path_parser = subparsers.add_parser('note-path', help='根据 collection path 和 MethodName 规划 Obsidian 保存路径')
    note_path_parser.add_argument('method_name', help='方法名 / 系统名')
    note_path_parser.add_argument('--collection-path', default='', help='选定的 Zotero collection 完整路径')
    note_path_parser.add_argument('--paper-notes-root', default=str(paper_notes_dir()), help='PaperNotes 根目录')
    note_path_parser.add_argument('--existing', action='append', default=[], help='已有同名笔记路径，可重复传入')
    note_path_parser.add_argument('--batch', action='store_true', help='批量模式：目标已存在时默认 skip')
    note_path_parser.add_argument('--zotero-item-id', type=int, help='写入 frontmatter 的 Zotero itemID')
    note_path_parser.add_argument('--doi', help='写入 frontmatter 并用于查重的 DOI')
    note_path_parser.add_argument('--arxiv-id', help='写入 frontmatter 并用于查重的 arXiv ID')
    note_path_parser.add_argument('--title', help='写入 frontmatter 并用于查重的论文标题')

    # 添加到分类
    add_parser = subparsers.add_parser('add-to-collection', help='将论文添加到分类')
    add_parser.add_argument('item_id', type=int, help='论文 ItemID')
    add_parser.add_argument('collection_id', type=int, help='目标分类ID')

    # 从分类移除
    remove_parser = subparsers.add_parser('remove-from-collection', help='从分类移除论文')
    remove_parser.add_argument('item_id', type=int, help='论文 ItemID')
    remove_parser.add_argument('collection_id', type=int, help='分类ID')

    # 移动到新分类
    move_parser = subparsers.add_parser('move', help='移动论文到新分类')
    move_parser.add_argument('item_id', type=int, help='论文 ItemID')
    move_parser.add_argument('new_collection_id', type=int, help='新分类ID')
    move_parser.add_argument('--from', dest='old_collection_id', type=int, help='旧分类ID（可选）')

    args = parser.parse_args()
    warn_if_deprecated_command(args.command or "")

    if not ZOTERO_DB.exists() and args.command not in {'note-path'}:
        print(f"Zotero 数据库不存在: {ZOTERO_DB}")
        return

    if args.command == 'add-to-collection':
        add_to_collection_db(args.item_id, args.collection_id)
        return
    if args.command == 'remove-from-collection':
        remove_from_collection_db(args.item_id, args.collection_id)
        return
    if args.command == 'move':
        move_to_collection(args.item_id, args.new_collection_id, args.old_collection_id)
        return
    if args.command == 'note-path':
        print_json(
            plan_note_save(
                Path(args.paper_notes_root),
                args.method_name,
                args.collection_path,
                existing_paths=[Path(path) for path in args.existing] if args.existing else None,
                batch=args.batch,
                zotero_item_id=args.zotero_item_id,
                doi=args.doi,
                arxiv_id=args.arxiv_id,
                title=args.title,
            )
        )
        return

    conn = copy_db()

    try:
        if args.command == 'collections':
            list_collections(conn)
        elif args.command == 'papers':
            list_papers_in_collection(conn, args.collection_id, recursive=args.recursive)
        elif args.command == 'search':
            search_paper(conn, args.keyword)
        elif args.command == 'pdf':
            get_pdf_path(conn, args.item_id)
        elif args.command == 'info':
            get_paper_info(conn, args.item_id)
        elif args.command == 'find-collection':
            find_collection_by_name(conn, args.name)
        elif args.command == 'resolve':
            if args.query:
                print_json(
                    {
                        "mode": "query",
                        "query": args.query,
                        "items": search_item_records(conn, args.query, limit=args.limit),
                    }
                )
            elif args.item_id:
                print_json({"mode": "item", "item": build_item_record(conn, args.item_id)})
            else:
                if args.collection_id:
                    candidates = [build_collection_record(conn, args.collection_id)]
                else:
                    candidates = find_collections(conn, args.collection)

                if len(candidates) != 1:
                    print_json(
                        {
                            "mode": "collection",
                            "query": args.collection,
                            "collection_candidates": candidates,
                            "items": [],
                        }
                    )
                else:
                    collection = candidates[0]
                    print_json(
                        {
                            "mode": "collection",
                            "collection": collection,
                            "recursive": args.recursive,
                            "items": resolve_items_for_collection(
                                conn,
                                collection["collection_id"],
                                recursive=args.recursive,
                            ),
                        }
                    )
        else:
            parser.print_help()
    finally:
        close_copied_db(conn)


if __name__ == '__main__':
    main()
