"""
Entity and relation extraction service.

Extracts named entities (persons, organizations, locations, dates, topics)
and relations ("works at", "met", "lives in", etc.) from memory text using
regex patterns ported from ZimMemory.

Provides async helpers to persist entities and relations to a tenant DB.
"""

import re
import time
import uuid
from typing import Optional

import aiosqlite


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_entity_name(name: str) -> str:
    """Remove punctuation, lowercase, and strip whitespace.

    Args:
        name: Raw entity name string.

    Returns:
        Normalized string suitable for dedup lookups.
    """
    return re.sub(r"[^a-z0-9\s]", "", name.lower()).strip()


# ---------------------------------------------------------------------------
# Entity patterns (compiled at module load for performance)
# ---------------------------------------------------------------------------

# Organization: word sequence ending in a known corporate suffix.
# The prefix is 1-3 capitalized words before the suffix.
_ORG_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9&\.\-]+(?:\s+[A-Z][A-Za-z0-9&\.\-]+){0,2}"
    r"\s+(?:Inc\.?|Corp\.?|LLC|Ltd\.?|Co\.?|Company|Group|Institute"
    r"|Foundation|University|College|School|Association|Agency|Bureau"
    r"|Department|Ministry))\b"
)

# Person: 1–3 capitalized words. Single capitalized words are included (e.g., "Alice").
# Uses a word boundary to avoid matching mid-word uppercase.
_PERSON_PATTERN = re.compile(
    r"\b([A-Z][a-z]{1,20}(?:\s[A-Z][a-z]{1,20}){0,2})\b"
)

# Location: "in/at/near/from/to <Capitalized Word(s)>"
# Negative lookahead to avoid matching known corporate suffixes as locations
_ORG_SUFFIX_RE = re.compile(
    r"(?:Inc\.?|Corp\.?|LLC|Ltd\.?|Co\.?|Company|Group|Institute"
    r"|Foundation|University|College|School|Association|Agency|Bureau"
    r"|Department|Ministry)$",
    re.IGNORECASE,
)
_LOCATION_IN_PATTERN = re.compile(
    r"\b(?:in|at|near|from|to|towards?)\s+([A-Z][a-z]{2,25}(?:\s+[A-Z][a-z]{2,25})?)\b"
)

# Well-known multi-word city/country names
_LOCATION_STANDALONE_PATTERN = re.compile(
    r"\b(New\s+(?:York|Jersey|Mexico|Orleans|Hampshire|Zealand)"
    r"|Los\s+Angeles|San\s+Francisco|Hong\s+Kong"
    r"|United\s+(?:States|Kingdom)|South\s+Korea|North\s+Korea"
    r"|Las\s+Vegas|Washington\s+D\.?C\.?|Washington\s+DC"
    r"|Rio\s+de\s+Janeiro|Buenos\s+Aires|Cape\s+Town)\b"
)

# Date: ISO (2024-01-15), Month + Day + Year, Month + Year, relative
_DATE_MONTH_DAY_YEAR_PATTERN = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August"
    r"|September|October|November|December)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{4})\b"
)
_DATE_MONTH_YEAR_PATTERN = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August"
    r"|September|October|November|December)\s+\d{4})\b"
)
_DATE_ISO_PATTERN = re.compile(
    r"\b(\d{4}-\d{2}-\d{2})\b"
)
_DATE_RELATIVE_PATTERN = re.compile(
    r"\b(last\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|week|month|year)"
    r"|(?:this|next)\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|week|month|year)"
    r"|yesterday|today|tomorrow)\b",
    re.IGNORECASE,
)

# Topic: "about X", "regarding X", "concerning X"
_TOPIC_PATTERN = re.compile(
    r"\b(?:about|regarding|concerning|related\s+to|on\s+the\s+topic\s+of)"
    r"\s+([A-Za-z][A-Za-z0-9\s]{2,30}?)(?:[.,;!?]|$)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Relation patterns
# ---------------------------------------------------------------------------

_RELATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+works?\s+at\s+([A-Z][A-Za-z0-9\s&\.]{1,40}?)(?=\s+(?:in|at|near|from|,|and|but|$)|\.|,|$)", re.IGNORECASE), "works_at"),
    (re.compile(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+met\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", re.IGNORECASE), "met"),
    (re.compile(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+lives?\s+in\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", re.IGNORECASE), "lives_in"),
    (re.compile(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+is\s+(?:a\s+|an\s+)?([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", re.IGNORECASE), "is"),
    (re.compile(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+founded?\s+([A-Z][A-Za-z0-9\s&\.]{1,40})", re.IGNORECASE), "founded"),
    (re.compile(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+manages?\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", re.IGNORECASE), "manages"),
    (re.compile(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+reports?\s+to\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", re.IGNORECASE), "reports_to"),
]


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def _collect_spans(matches: list) -> set[tuple[int, int]]:
    """Return a set of (start, end) span tuples from a list of Match objects."""
    return {m.span() for m in matches}


def extract_entities(text: str) -> list[dict]:
    """Extract named entities from text using regex patterns.

    Returns a list of entity dicts, each with keys:
        - name: str — raw matched name
        - type: "person" | "organization" | "location" | "date" | "topic"
        - span: (start, end) tuple of character offsets

    Entities are deduplicated by (name_normalized, type) — first occurrence wins.

    Args:
        text: Memory text to process.

    Returns:
        List of entity dicts, potentially empty.
    """
    entities: list[dict] = []
    seen: set[tuple[str, str]] = set()
    # Track all character positions claimed by higher-priority matches
    # to prevent lower-priority patterns from overlapping
    claimed: set[tuple[int, int]] = set()

    def _add(name: str, entity_type: str, span: tuple[int, int]) -> None:
        key = (normalize_entity_name(name), entity_type)
        if key not in seen and key[0]:
            seen.add(key)
            claimed.add(span)
            entities.append({"name": name.strip(), "type": entity_type, "span": span})

    def _overlaps_claimed(span: tuple[int, int]) -> bool:
        """Return True if span overlaps with any previously claimed span."""
        start, end = span
        for cs, ce in claimed:
            if start < ce and end > cs:
                return True
        return False

    # Priority order (highest to lowest):
    # 1. Organizations (corporate suffix anchors are unambiguous)
    # 2. Dates (month names, ISO, relative — must claim before person matches "January")
    # 3. Standalone known multi-word locations ("New York" etc.)
    # 4. Location-in patterns (preposition-anchored)
    # 5. Persons (most general — runs last to avoid claiming org/date/location text)
    # 6. Topics

    # 1. Organizations
    for m in _ORG_PATTERN.finditer(text):
        _add(m.group(1), "organization", m.span(1))

    # 2. Dates (most specific first, so "January 15, 2024" beats "January 2024")
    for m in _DATE_MONTH_DAY_YEAR_PATTERN.finditer(text):
        if not _overlaps_claimed(m.span(1)):
            _add(m.group(1), "date", m.span(1))
    for m in _DATE_MONTH_YEAR_PATTERN.finditer(text):
        if not _overlaps_claimed(m.span(1)):
            _add(m.group(1), "date", m.span(1))
    for m in _DATE_ISO_PATTERN.finditer(text):
        if not _overlaps_claimed(m.span(1)):
            _add(m.group(1), "date", m.span(1))
    for m in _DATE_RELATIVE_PATTERN.finditer(text):
        if not _overlaps_claimed(m.span(1)):
            _add(m.group(1), "date", m.span(1))

    # 3. Standalone known multi-word locations (before persons — "New York" etc.)
    for m in _LOCATION_STANDALONE_PATTERN.finditer(text):
        if not _overlaps_claimed(m.span()):
            _add(m.group(0), "location", m.span())

    # 4. Location-in patterns (preposition + capitalized name)
    for m in _LOCATION_IN_PATTERN.finditer(text):
        name = m.group(1)
        # Skip if the captured name ends with an org suffix (e.g., "Google Inc")
        if _ORG_SUFFIX_RE.search(name):
            continue
        if not _overlaps_claimed(m.span(1)):
            _add(name, "location", m.span(1))

    # 5. Persons — skip any match whose span overlaps previously claimed spans
    for m in _PERSON_PATTERN.finditer(text):
        if not _overlaps_claimed(m.span(1)):
            _add(m.group(1), "person", m.span(1))

    # 6. Topics
    for m in _TOPIC_PATTERN.finditer(text):
        if not _overlaps_claimed(m.span(1)):
            _add(m.group(1).strip(), "topic", m.span(1))

    return entities


# ---------------------------------------------------------------------------
# Relation extraction
# ---------------------------------------------------------------------------

def extract_relations(text: str, entities: list[dict]) -> list[dict]:
    """Extract relations between entities in text.

    Uses regex patterns for common relation types. Source and target types are
    resolved by matching against the provided entities list; defaults to
    "unknown" if an entity name is not found in the list.

    Args:
        text: Memory text.
        entities: List of entity dicts from extract_entities().

    Returns:
        List of relation dicts with keys:
            source, relationship, target, source_type, target_type
    """
    relations: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    # Build a name→type lookup (normalized → original type)
    entity_type_map: dict[str, str] = {}
    for ent in entities:
        key = normalize_entity_name(ent["name"])
        if key:
            entity_type_map[key] = ent["type"]

    def _get_type(name: str) -> str:
        return entity_type_map.get(normalize_entity_name(name), "unknown")

    for pattern, relationship in _RELATION_PATTERNS:
        for m in pattern.finditer(text):
            source = m.group(1).strip()
            target = m.group(2).strip()
            key = (normalize_entity_name(source), relationship, normalize_entity_name(target))
            if key not in seen and key[0] and key[2]:
                seen.add(key)
                relations.append({
                    "source": source,
                    "relationship": relationship,
                    "target": target,
                    "source_type": _get_type(source),
                    "target_type": _get_type(target),
                })

    return relations


# ---------------------------------------------------------------------------
# DB persistence helpers
# ---------------------------------------------------------------------------

async def find_or_create_entity(
    conn: aiosqlite.Connection,
    name: str,
    entity_type: str,
) -> str:
    """Return the entity_id for name, creating a new row if it doesn't exist.

    Lookup is by name_normalized to handle case/punctuation variants.

    Args:
        conn: Open aiosqlite connection to a tenant DB.
        name: Raw entity name.
        entity_type: One of "person", "organization", "location", "date", "topic".

    Returns:
        entity_id string (UUID).
    """
    name_normalized = normalize_entity_name(name)
    if not name_normalized:
        raise ValueError(f"Cannot create entity with empty normalized name: {name!r}")

    # Check if exists
    async with conn.execute(
        "SELECT id FROM entities WHERE name_normalized = ? AND entity_type = ?",
        (name_normalized, entity_type),
    ) as cur:
        row = await cur.fetchone()

    if row is not None:
        entity_id = row[0]
        # Increment mention_count and update last_seen_at
        now = int(time.time())
        await conn.execute(
            "UPDATE entities SET mention_count = mention_count + 1, last_seen_at = ? WHERE id = ?",
            (now, entity_id),
        )
        await conn.commit()
        return entity_id

    # Create new entity
    entity_id = str(uuid.uuid4())
    now = int(time.time())
    await conn.execute(
        """
        INSERT INTO entities (id, name, name_normalized, entity_type, created_at, mention_count, last_seen_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (entity_id, name.strip(), name_normalized, entity_type, now, now),
    )
    await conn.commit()
    return entity_id


async def process_entities_for_memory(
    conn: aiosqlite.Connection,
    memory_id: str,
    text: str,
) -> dict:
    """Orchestrate entity/relation extraction and persistence for a memory.

    Extracts entities and relations from text, persists them to the entities
    and relations tables, and links each relation back to memory_id.

    Args:
        conn: Open aiosqlite connection to a tenant DB.
        memory_id: The ID of the memory being processed.
        text: The raw memory text.

    Returns:
        Dict with keys:
            - entities_found: int — number of unique entities extracted
            - relations_found: int — number of unique relations extracted
    """
    entities = extract_entities(text)
    relations = extract_relations(text, entities)

    # Persist entities and build id lookup
    entity_id_map: dict[str, str] = {}
    for ent in entities:
        normalized = normalize_entity_name(ent["name"])
        entity_id = await find_or_create_entity(conn, ent["name"], ent["type"])
        entity_id_map[normalized] = entity_id

    # Persist relations
    now = int(time.time())
    for rel in relations:
        source_normalized = normalize_entity_name(rel["source"])
        target_normalized = normalize_entity_name(rel["target"])

        source_id = entity_id_map.get(source_normalized)
        target_id = entity_id_map.get(target_normalized)

        # If either entity wasn't in our extracted list, try to find/create
        if source_id is None:
            source_id = await find_or_create_entity(conn, rel["source"], rel["source_type"])
            entity_id_map[source_normalized] = source_id
        if target_id is None:
            target_id = await find_or_create_entity(conn, rel["target"], rel["target_type"])
            entity_id_map[target_normalized] = target_id

        relation_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO relations
                (id, source_entity_id, source_name, source_type, relationship,
                 target_entity_id, target_name, target_type, memory_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relation_id,
                source_id,
                rel["source"],
                rel["source_type"],
                rel["relationship"],
                target_id,
                rel["target"],
                rel["target_type"],
                memory_id,
                now,
            ),
        )
    await conn.commit()

    return {
        "entities_found": len(entities),
        "relations_found": len(relations),
    }
