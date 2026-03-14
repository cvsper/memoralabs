---
phase: 06-deployment-launch
plan: 03
subsystem: deploy
tags: [render, smoke-test, production, verification, persistence]

# Dependency graph
requires:
  - phase: 06-01
    provides: render.yaml, disk mount guard
  - phase: 06-02
    provides: enhanced health endpoint, smoke-test script
provides:
  - Live production deployment at https://memoralabs-api.onrender.com
  - Verified data persistence across deploys
  - Confirmed starter plan eliminates cold-start
affects: []

# Tech tracking
tech-stack:
  added: [docker]
  patterns:
    - Docker runtime required for hnswlib C++ compilation on Render
    - python:3.11-slim + build-essential base image
    - Background embedding needs ~3s before vector search returns results

key-files:
  created:
    - Dockerfile
  modified:
    - render.yaml
    - scripts/smoke-test.sh

key-decisions:
  - "Docker runtime instead of native Python — hnswlib requires C++ build tools"
  - "maxShutdownDelaySeconds removed — Render does not support it with persistent disk"
  - "smoke-test.sh uses sed '$d' instead of head -n -1 for macOS compatibility"
  - "3s delay before search step to allow background embedding indexing"

# Metrics
duration: 10min
completed: 2026-03-14
---

# Phase 6 Plan 03: Launch Verification — Summary

**Live Render deployment verified end-to-end: health, signup, store, search, gaps all passing at public URL**

## Performance

- **Duration:** ~10 min (includes deploy debugging)
- **Completed:** 2026-03-14

## Accomplishments
- Deployed MemoraLabs to Render at https://memoralabs-api.onrender.com
- Switched from native Python runtime to Docker (hnswlib C++ requirement)
- Removed maxShutdownDelaySeconds (not supported with persistent disk)
- Fixed smoke-test.sh: macOS compat, correct field names (text not content), correct gaps endpoint path
- Ran full smoke test — 5/5 passing: health, signup, store memory, search, gap detection
- Verified persistent disk mounted (disk_mounted: true in /health response)
- Confirmed starter plan = always-on, no cold-start

## Deviations from Plan

### Auto-fixed Issues

**1. Render native Python runtime lacks C++ compiler for hnswlib**
- Added Dockerfile with python:3.11-slim + build-essential
- Changed render.yaml from runtime: python to runtime: docker

**2. maxShutdownDelaySeconds not supported with disk**
- Render rejects this field when a persistent disk is attached
- Removed from render.yaml

**3. smoke-test.sh field name mismatches**
- `content` → `text` (matches MemoryCreate model)
- Missing `name` field in signup
- `/v1/intelligence/gaps` → `/v1/memory/gaps`
- `head -n -1` → `sed '$d'` (macOS compatible)
- Added 3s delay before search for background embedding indexing

## Issues Encountered
- Deploy failed twice before succeeding (render.yaml fixes)
- Smoke test required 3 iterations to fix field mismatches

## User Setup Required
None — deployment is live and verified.
