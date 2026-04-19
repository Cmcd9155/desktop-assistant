# MVP1 Desktop Assistant Plan v2 (Question-Locked Replacement)

## Summary
- Build a local desktop-style app with Python (FastAPI) backend and Vite + React + TypeScript frontend, launched in a dedicated browser window.
- Keep one primary chat agent; no specialist agents.
- Use xAI image APIs for per-turn companion updates with a fixed base image anchor and async image jobs.
- Bridge to OpenClaw via a dedicated session and polling, ingesting only tagged responses.
- Use mem0 for long-term memory with a cavemem-inspired terse summarization pass and latency-based write triggers.
- Use the animated companion SDK project in the parent folder as a reference implementation, while intentionally favoring simpler architecture and fewer moving parts for MVP1.

## Key Implementation Changes

### Core runtime
- `POST /api/chat/turn` returns text immediately plus `imageJobId`; image generation never blocks text.
- Companion state model includes `idle | thinking | smiling | frowning | moderated`.
- Fixed base image from settings is always passed as reference for turn image updates (no rolling-anchor drift).

### Image pipeline (xAI)
- Primary model path uses xAI image generation/edit APIs with explicit character/style template (including explicit NSFW allowance).
- On moderation/rejection/failure: keep previous valid image, mark companion as moderated, and show a toast explaining moderation fallback.
- Persist generated image bytes locally immediately (do not rely on temporary provider URLs).

### OpenClaw bridge
- Use dedicated OpenClaw session key for this app.
- Outbound messages are tagged with app request IDs; polling ingests only matching tagged responses.
- Polling is bounded and idempotent (cursor + dedupe key) to prevent loops/duplicate timeline events.

### Memory subsystem (mem0 + "caveman" concept)
- Memory writes are not per-turn; they run when conversation is likely concluded:
  - inactivity gap > 30 minutes, or
  - user clicks settings control that disables memory system / closes session.
- Before mem0 write, run a summarizer-agent pass that stores only terse, high-value memories (goals, decisions, durable preferences, important constraints).
- Add settings toggle `Memory System Enabled`; turning it off forces one final flush then pauses further memory writes.

### Settings and UI
- Settings page supports base image upload, core bio/instructions edit, memory query, memory wipe, and memory enable/disable toggle.
- Companion panel animations map to response/emotion and moderation state.
- Desktop launcher script starts backend + frontend and opens app window URL.

### Build guidance (reference-first, simplify-by-default)
- Use the parent-folder animated companion SDK project as a pattern source for animation behavior, rendering patterns, and companion UX decisions.
- Do not mirror the reference project wholesale; copy only what directly supports MVP1 requirements.
- Prefer a single clear path per feature over abstractions or plugin-style extensibility.
- Keep module boundaries minimal and explicit so the runtime is easy to reason about and debug locally.
- When a reference-inspired design adds complexity without clear MVP1 value, choose the simpler implementation.

### External API research requirement (xAI)
- For any xAI integration task, perform online research first to confirm current API endpoints, request/response contracts, auth requirements, model capabilities, limits, and error/moderation behavior.
- Prefer official xAI documentation and primary sources; do not rely on stale assumptions.
- Re-verify endpoint details when implementing new xAI features or when behavior changes are observed.

## Public Interfaces / Types

### API endpoints
- `POST /api/chat/turn` -> `{ replyText, imageJobId, emotion, openclawRequestId?, warnings[] }`
- `GET /api/chat/image/:jobId` -> `{ status, imageUrl?, moderated?, errorCode? }`
- `GET/PUT /api/settings/companion` -> `{ bio, baseImagePath, nsfwEnabled, memoryEnabled }`
- `GET /api/memory?query=...` -> `{ items[] }`
- `DELETE /api/memory` -> `{ ok }`
- `POST /api/openclaw/send` -> `{ requestId, sessionKey, accepted }`
- `GET /api/openclaw/poll` -> `{ events[], cursor }`
- `POST /api/memory/flush` -> `{ writtenCount, summaryId }` (internal/admin endpoint, used by inactivity and toggle flows)

### Internal data contracts
- `ImageJob: { id, turnId, promptHash, status, moderated, outputPath, createdAt, completedAt }`
- `MemoryFlushEvent: { trigger: inactivity|toggle_off|shutdown, conversationRange, summaryText, storedAt }`
- `OpenClawBridgeEvent: { requestId, sourceSession, role, text, ts }`

## Test Plan

### Test layers and cadence
- Smoke tests run on every PR and on local startup checks.
- Unit tests run on every commit/PR.
- Integration tests run on every PR.
- Live AI tests (real UI + real model/provider calls) run nightly and before release candidates.

### Smoke tests (fast, fail-fast checks)
- Launcher starts backend + frontend, app window URL opens, and health endpoints respond.
- `POST /api/chat/turn` returns quickly with `replyText` and `imageJobId` (text-first behavior).
- `GET /api/chat/image/:jobId` reaches a terminal state (`completed`, `moderated`, or `failed`) within timeout.
- `GET/PUT /api/settings/companion` roundtrip works and persists expected values.
- OpenClaw bridge basic flow works: `/api/openclaw/send` accepts and `/api/openclaw/poll` returns only tagged events.
- Memory endpoints are reachable: `GET /api/memory`, `POST /api/memory/flush`, `DELETE /api/memory`.

### Unit tests
- Emotion mapping and companion state transitions (`idle`, `thinking`, `smiling`, `frowning`, `moderated`).
- Prompt builder invariants: fixed base image must be included every turn; no rolling-anchor drift.
- Image job state machine: queued -> running -> completed/moderated/failed, with deterministic fallback to previous valid image.
- OpenClaw filtering and idempotency: tag-match-only ingest, cursor progression, dedupe key handling.
- Memory summarizer compression: output is terse and high-signal (goals, decisions, durable preferences, constraints).
- Memory write trigger logic: per-turn writes blocked, inactivity window triggers flush, `memoryEnabled=false` forces final flush then blocks new writes.

### Integration tests
- Text-first turn returns immediately while image job resolves asynchronously.
- Moderated image path surfaces UI toast, keeps previous valid image, and marks companion as moderated.
- Dedicated OpenClaw session send/poll roundtrip ingests only matching tagged response events.
- Inactivity trigger (>30 min) writes mem0 summary; per-turn writes do not occur.
- `memoryEnabled=false` triggers flush and then blocks subsequent memory writes.
- Settings update for `baseImagePath` affects the next generated image prompt contract.

### Live AI tests (agent-driven app verification)
- Use browser automation (`Playwright`) plus an evaluator agent that drives the app like a user and checks UI + API evidence.
- Scenario 1: 3-turn conversation produces expression changes while maintaining stable companion identity.
- Scenario 2: explicit NSFW request where provider allows generation; verify updated image appears and is persisted locally.
- Scenario 3: explicit NSFW request where provider moderates/rejects; verify toast appears, previous image remains, companion state is `moderated`.
- Scenario 4: disable memory in settings; verify one final flush event then no new memory writes.
- Scenario 5: inactivity-based flush (test-configurable short window in CI) writes exactly one summary event.
- Scenario 6: OpenClaw tagged response appears in timeline once (no duplicates across repeated polls).

### Live test pass/fail rules
- Assertions should be contract-based, not exact text matching (allow model variance).
- Each live test stores artifacts: screenshots, request/response logs, and timeline/event traces.
- A live test fails on contract breakage, missing artifact, timeout, duplicate ingest, or silent moderation fallback.

### CI gating
- PR required checks: smoke + unit + integration suites with mocked external provider calls where needed.
- Nightly scheduled checks: live AI suite against real providers and local OpenClaw bridge.
- Release gate: last nightly live AI run must be green within 24 hours of release cut.

## Assumptions and Defaults
- OpenClaw runs locally and supports `/v1/responses` on the configured gateway; dedicated session key is available.
- Default poll interval: 5s; default image job timeout: 45s; default memory inactivity window: 30min.
- Explicit NSFW is allowed by product intent; provider moderation may still reject individual prompts.
- Caveman integration is concept-level for MVP1 (terse compression/summarization behavior), not a hard dependency on external cavemem binaries.
- Single-user local desktop target for MVP1; multi-user auth and cloud deployment are deferred.
