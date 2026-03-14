# MemoraLabs

## What This Is

MemoraLabs is a memory-as-a-service API platform for AI agent developers. It gives AI agents persistent, self-improving memory with temporal decay, entity graphs, and reinforcement-learned retrieval — so agents get smarter over time, not just bigger. Built on ZimMemory v15 (3,395 memories, 15 major versions of production usage across a 6-agent fleet).

## Core Value

Agents that remember intelligently — memory that improves its own retrieval over time, not just stores and fetches.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Developer can sign up and get an API key
- [ ] Developer can store memories via API
- [ ] Developer can recall memories with intelligent retrieval
- [ ] Developer can create isolated memory namespaces (multi-tenant)
- [ ] Memory retrieval improves over time (Q-learning router)
- [ ] Memories decay naturally based on relevance and time
- [ ] Entity extraction and graph-enhanced retrieval
- [ ] Knowledge gap detection
- [ ] API docs available on the website
- [ ] Landing page explains product and pricing
- [ ] Deploy to cloud (Render) — not local Mac Mini

### Out of Scope

- Dashboard UI — API-first for v1, devs don't need a GUI
- Stripe billing — manual onboarding or waitlist first, add payments later
- Multi-agent shared memory — v2 feature (lead with single-agent first, expand)
- Mobile SDKs — REST API only for v1
- Self-hosting option — cloud-only for v1

## Context

- **Existing codebase**: ZimMemory v15 on Mac Mini (~/zim_memory/server.py). Python/Flask, SQLite, Fireworks.ai embeddings (mxbai-embed-large-v1 1024-dim), Q-learning router, GraphRAG, temporal decay, entity resolution, PageRank, knowledge gaps.
- **Battle-tested**: 3,395 memories, 854 entities, 1,249 relations. Running in production across 6 AI agents for months.
- **Competitors**: Mem0 (broad/general), Zep (enterprise), LangMem (LangChain-coupled), Letta (OS-inspired). No one owns "self-improving memory" as a positioning.
- **Domain**: memoralabs.io (available). Working name: MemoraLabs.
- **Target**: Individual developers and startups building AI agent products.

## Constraints

- **Tech stack**: Python/Flask — our core competency, matches existing ZimMemory codebase
- **Database**: SQLite per tenant for v1 (simple, isolated), PostgreSQL migration path for v2
- **Embeddings**: Fireworks.ai (mxbai-embed-large-v1) — existing integration, free tier 60 req/min
- **Hosting**: Render free/starter tier for MVP
- **Timeline**: Ship MVP today (March 14, 2026)
- **Budget**: $0 infrastructure cost for launch (free tiers only)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Lead with self-improving memory, not multi-agent | Clearer differentiator vs Mem0/Zep, easier to explain | — Pending |
| SQLite per tenant | Simple isolation, no shared DB complexity for v1 | — Pending |
| Fireworks.ai for embeddings | Already integrated in ZimMemory, free tier sufficient | — Pending |
| Flask not FastAPI | Matches existing codebase, team expertise | — Pending |
| No Stripe for v1 | Ship faster, validate demand before billing complexity | — Pending |
| Target devs + startups | Lower sales cycle, self-serve, matches API-first approach | — Pending |

---
*Last updated: 2026-03-14 after initialization*
