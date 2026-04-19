# Desktop Assistant (MVP1)

Local-first desktop assistant with:
- FastAPI backend (`backend/`)
- Vite + React + TypeScript frontend (`frontend/`)
- Async text-first chat turns with background image jobs
- xAI image generation/edit pipeline with moderation fallback
- OpenClaw tagged bridge with cursor + dedupe polling
- mem0-style long-term memory with inactivity/toggle-off flush triggers

## Quick start

### 1) Backend
```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --app-dir .
```

### 2) Frontend
```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`.

## Desktop launcher

- Linux/WSL: `./scripts/launch-desktop.sh`
- Windows PowerShell: `./scripts/launch-desktop.ps1`
- Stop stack (Linux/WSL): `./scripts/stop-desktop.sh`
- Stop stack (PowerShell): `./scripts/stop-desktop.ps1`

The launchers are idempotent:
- They report when backend/frontend/OpenClaw are already running.
- They only start missing components.
- They print runtime status and log file paths.

## Backend API

- `POST /api/chat/turn` -> `{ replyText, imageJobId, emotion, openclawRequestId?, warnings[] }`
- `GET /api/chat/image/:jobId` -> `{ status, imageUrl?, moderated?, errorCode? }`
- `GET/PUT /api/settings/companion` -> `{ bio, instructions, baseImagePath, nsfwEnabled, memoryEnabled }`
- `POST /api/settings/companion/base-image` (multipart upload)
- `GET /api/memory?query=...` -> `{ items[] }`
- `DELETE /api/memory` -> `{ ok }`
- `POST /api/memory/flush` -> `{ writtenCount, summaryId }`
- `POST /api/openclaw/send` -> `{ requestId, sessionKey, accepted }`
- `GET /api/openclaw/poll` -> `{ events[], cursor }`

## Tests

From `backend/`:

```bash
pytest app/tests/smoke -q
pytest app/tests/unit -q
pytest app/tests/integration -q
```

Live suite (nightly CI + optional local):
```bash
RUN_LIVE_AI_TESTS=1 XAI_API_KEY=... pytest app/tests/live -m live -q
```

## xAI image integration notes

- Uses `https://api.x.ai/v1/images/generations` and `https://api.x.ai/v1/images/edits`
- Uses `response_format: b64_json` when available and persists image bytes locally immediately
- Falls back to previous valid image on moderation/rejection/failure
