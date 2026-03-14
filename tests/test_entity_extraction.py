"""Tests for app/services/entity_extraction.py."""
import uuid
import aiosqlite
import pytest
import pytest_asyncio
from app.db.tenant import init_tenant_db
from app.services.dedup import text_hash
from app.services.entity_extraction import (
    extract_entities,
    extract_relations,
    find_or_create_entity,
    normalize_entity_name,
    process_entities_for_memory,
)

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest_asyncio.fixture
async def tenant_conn():
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = aiosqlite.Row
    await init_tenant_db(conn)
    yield conn
    await conn.close()

# normalize_entity_name
def test_normalize_entity_name():
    assert normalize_entity_name("Alice Smith!") == "alice smith"
    assert normalize_entity_name("Google, Inc.") == "google inc"
    assert normalize_entity_name("  New York  ") == "new york"
    assert normalize_entity_name("O'Brien") == "obrien"

# extract_entities - persons
def test_extract_person_two_names():
    ents = extract_entities("Alice met Bob")
    persons = [e for e in ents if e["type"] == "person"]
    names = {e["name"] for e in persons}
    assert "Alice" in names or "Bob" in names, f"Expected person, got: {ents}"

def test_extract_person_single_capitalized():
    ents = extract_entities("Alice called today")
    persons = [e for e in ents if e["type"] == "person"]
    assert len(persons) >= 1, f"Expected person, got: {ents}"

def test_extract_person_full_name():
    ents = extract_entities("John Smith joined the team")
    persons = [e for e in ents if e["type"] == "person"]
    names = {e["name"] for e in persons}
    assert "John Smith" in names, f"Expected John Smith: {names}"

# organizations
def test_extract_organization():
    ents = extract_entities("works at Google Inc")
    orgs = [e for e in ents if e["type"] == "organization"]
    names = {e["name"] for e in orgs}
    assert any("Google Inc" in n for n in names), f"Expected Google Inc: {ents}"

def test_extract_organization_corp():
    ents = extract_entities("Microsoft Corp announced results")
    orgs = [e for e in ents if e["type"] == "organization"]
    assert len(orgs) >= 1, f"Expected org: {ents}"

# locations
def test_extract_location():
    ents = extract_entities("lives in New York")
    locs = [e for e in ents if e["type"] == "location"]
    assert len(locs) >= 1, f"Expected location: {ents}"
    names = {e["name"] for e in locs}
    assert "New York" in names, f"Expected New York: {names}"

def test_extract_location_standalone():
    ents = extract_entities("He moved to Los Angeles last year")
    locs = [e for e in ents if e["type"] == "location"]
    assert len(locs) >= 1, f"Expected location: {ents}"

# dates
def test_extract_date_month_day_year():
    ents = extract_entities("on January 15, 2024")
    dates = [e for e in ents if e["type"] == "date"]
    assert len(dates) >= 1, f"Expected date: {ents}"
    assert "January 15, 2024" in {e["name"] for e in dates}

def test_extract_date_month_year():
    ents = extract_entities("in January 2024")
    dates = [e for e in ents if e["type"] == "date"]
    assert len(dates) >= 1, f"Expected date: {ents}"

def test_extract_date_iso():
    ents = extract_entities("created on 2024-01-15")
    dates = [e for e in ents if e["type"] == "date"]
    assert len(dates) >= 1, f"Expected ISO date: {ents}"
    assert "2024-01-15" in {e["name"] for e in dates}

# edge cases
def test_extract_no_entities():
    ents = extract_entities("hello world")
    assert ents == [], f"Expected empty list: {ents}"

def test_extract_multiple_types():
    ents = extract_entities("Alice Smith works at Acme Corp in Paris on January 2024")
    types = {e["type"] for e in ents}
    assert len(types) >= 2, f"Expected multiple entity types: {ents}"

# relations
def test_extract_relations_works_at():
    ents = extract_entities("Alice works at Google Inc")
    rels = extract_relations("Alice works at Google Inc", ents)
    assert any(r["relationship"] == "works_at" for r in rels), f"Expected works_at: {rels}"

def test_extract_relations_met():
    ents = extract_entities("Alice met Bob")
    rels = extract_relations("Alice met Bob", ents)
    assert any(r["relationship"] == "met" for r in rels), f"Expected met: {rels}"

def test_extract_relations_lives_in():
    ents = extract_entities("Alice lives in Seattle")
    rels = extract_relations("Alice lives in Seattle", ents)
    assert any(r["relationship"] == "lives_in" for r in rels), f"Expected lives_in: {rels}"

# DB persistence
@pytest.mark.anyio
async def test_find_or_create_entity_creates(tenant_conn):
    entity_id = await find_or_create_entity(tenant_conn, "Alice Smith", "person")
    assert isinstance(entity_id, str)
    assert len(entity_id) == 36
    async with tenant_conn.execute(
        "SELECT id, name, entity_type FROM entities WHERE id = ?", (entity_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["name"] == "Alice Smith"
    assert row["entity_type"] == "person"

@pytest.mark.anyio
async def test_find_or_create_entity_finds_existing(tenant_conn):
    id1 = await find_or_create_entity(tenant_conn, "Google Inc", "organization")
    id2 = await find_or_create_entity(tenant_conn, "Google Inc", "organization")
    assert id1 == id2

@pytest.mark.anyio
async def test_find_or_create_entity_increments_mention_count(tenant_conn):
    entity_id = await find_or_create_entity(tenant_conn, "Bob Johnson", "person")
    await find_or_create_entity(tenant_conn, "Bob Johnson", "person")
    async with tenant_conn.execute(
        "SELECT mention_count FROM entities WHERE id = ?", (entity_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row["mention_count"] == 2

@pytest.mark.anyio
async def test_process_entities_for_memory(tenant_conn):
    memory_id = str(uuid.uuid4())
    await tenant_conn.execute(
        "INSERT INTO memories (id, text, text_hash, created_at) VALUES (?, ?, ?, ?)",
        (memory_id, "Alice met Bob", text_hash("Alice met Bob"), 1700000000),
    )
    await tenant_conn.commit()
    result = await process_entities_for_memory(tenant_conn, memory_id, "Alice met Bob")
    assert "entities_found" in result
    assert "relations_found" in result
    assert result["entities_found"] >= 1
    async with tenant_conn.execute("SELECT COUNT(*) FROM entities") as cur:
        row = await cur.fetchone()
    assert row[0] >= 1
