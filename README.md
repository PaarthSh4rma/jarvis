# JARVIS

A local-first personal assistant and developer command centre. V0.6 adds a bounded execution lifecycle, progressive local Ollama responses, observable tool progress, cancellation, and deterministic timeouts.

## Prerequisites

- macOS (primary development environment)
- Node.js 20+ and npm 10+
- Python 3.10+
- [Ollama for macOS](https://docs.ollama.com/macos)

## Setup

Install the web dependencies:

```bash
npm install
```

Create and populate the API virtual environment:

```bash
python3.11 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -e "apps/api[dev]"
```

Optional configuration:

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env.local
```

No secrets are required for this milestone. Environment files are ignored by Git.

### Configure Ollama

Start the Ollama application (or run `ollama serve`), then pull the configured local model:

```bash
ollama pull llama3.2:3b
```

The default configuration is:

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
PROJECTS_ROOT=/Users/your-name/Developer
CONVERSATION_TTL_SECONDS=1800
CONVERSATION_MAX_TURNS=12
CONVERSATION_MAX_CHARACTERS=12000
JARVIS_MEMORY_MAX_USER_ENTRIES=50
JARVIS_MEMORY_MAX_PROJECT_ENTRIES=25
JARVIS_MEMORY_MAX_CHARACTERS=500
JARVIS_MEMORY_MAX_INJECTED_CHARACTERS=2000
JARVIS_RUN_TIMEOUT_SECONDS=90
JARVIS_TOOL_TIMEOUT_SECONDS=15
JARVIS_RUN_TERMINAL_TTL_SECONDS=900
JARVIS_RUN_MAX_ENTRIES=100
JARVIS_RUN_MAX_EVENTS=200
```

Change `OLLAMA_MODEL` in the root `.env` and pull that same model to switch models without changing code. Model downloads can be large; choose one appropriate for the Mac running JARVIS.

Set `PROJECTS_ROOT` to the directory containing your software projects. JARVIS scans only its immediate child directories. A child is considered a project when it contains `.git`, `package.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`, or `go.mod`.

## Run locally

Use two terminals from the repository root:

```bash
apps/api/.venv/bin/uvicorn jarvis_api.main:app --app-dir apps/api --reload --port 8000
```

```bash
npm run dev:web
```

Open [http://localhost:3000](http://localhost:3000). The dashboard reports API and Ollama health independently. Messages travel only from the browser to FastAPI and from FastAPI to local Ollama; the browser never receives a general Ollama proxy.

If Ollama is stopped or the model is missing, the API remains healthy and reports the conversational runtime as offline. Chat requests return a controlled error rather than crashing the application.

Project-aware examples:

- `What projects do I have?`
- `Which projects have uncommitted changes?`
- `What branch is jarvis on?`
- `Open jarvis in VS Code.`

Opening a project is the only action in V0.3. It supports VS Code and Finder, requires explicit wording, and always resolves the target from the discovered project index.

### Short-term conversation context

The browser creates an opaque session on first use and retains its UUID locally. For refresh continuity, the current tab also keeps a bounded snapshot of completed user/assistant messages in `sessionStorage`: at most 24 messages and 12,000 characters. Active deltas and failed, cancelled, or timed-out exchanges are never added to that snapshot. The backend remains authoritative and keeps recent turns in memory for 30 minutes after the last request, with deterministic limits of 12 user turns and 12,000 characters. Older complete turns are dropped first; they are not summarised.

Use `NEW SESSION` beside the command interface to delete the current backend session, clear the visible transcript, and create a fresh context. Restarting the API also clears every session. Session turns remain short-term working context and are never written to SQLite.

Recent trusted project observations may resolve follow-ups such as `When was it last updated?` or `Which branch is the first one on?`. Ambiguous references prompt for clarification. Conversation context never supplies paths, grants launch permission, or bypasses project-ID and tool validation.

Approved project-tool observations are rendered by the backend rather than reinterpreted by the model. Explicit values such as `is_dirty: false` are authoritative; commit messages or prior dialogue cannot contradict them, and uncertainty is used only for missing, errored, or ambiguous fields.

### Persistent memory

Persistent memory is a separate, deliberately small collection of durable facts. User memory holds general preferences; project memory is attached to one opaque discovered-project identity. It survives sessions and backend restarts in the local SQLite database at `data/jarvis.db` by default. It never stores conversation transcripts.

Memory is written only through an explicit chat request such as `Remember that I prefer pnpm`, `For RaceBrain, remember that the backend normally uses port 8000`, or through the dashboard memory panel/API. `Forget the RaceBrain port memory` removes one unambiguous match; JARVIS asks for clarification when more than one memory matches. There is no background extraction.

The dashboard's compact `MEMORY` section switches between `USER MEMORY` and `PROJECT MEMORY` and supports viewing, adding, editing, and deleting entries. Equivalent API routes are:

- `GET /memory` with optional `scope` and `project_id` filters
- `POST /memory`
- `PATCH /memory/{memory_id}`
- `DELETE /memory/{memory_id}`

Defaults are 50 user entries, 25 entries per project, 500 characters per entry, and 2,000 injected memory characters. Project memory is injected only when the current request resolves that project unambiguously. Selection is deterministic and remains separate from the 12,000-character session bound.

Memory is contextual data, not authority. Precedence is `LIVE TRUSTED OBSERVATION > EXPLICIT CURRENT USER STATEMENT > PERSISTED MEMORY > MODEL INFERENCE`. Stored text cannot grant tool permission, change configured roots, override path validation, or supersede a current Git observation. Memory is clearly labelled as untrusted data in the model context, including text that resembles instructions. Entries containing common credential markers such as passwords, API keys, access tokens, secrets, or private keys are rejected; memory is not a secret store.

### Execution runtime

The dashboard starts a run with `POST /runs`, then reads structured events from `GET /runs/{run_id}/events` using Server-Sent Events. Assistant text is assembled from `assistant.delta` events and committed to short-term session history only once the run completes. `POST /runs/{run_id}/cancel` is ownership-checked by conversation ID and is safe to repeat. The existing `POST /chat` contract remains available for compatibility.

Only one run may be active per conversation; different conversations can run independently. Overall execution defaults to 90 seconds and each approved tool to 15 seconds. The in-memory store retains at most 100 runs, 200 events per run, and terminal runs for 15 minutes. A refresh detaches the browser from its current stream, restores the same conversation identity and previously completed tab-local transcript, and clears only uncommitted activity. The backend still reaches a terminal state. V0.6 does not automatically reconcile that detached result into the UI; submitting again while it remains active receives the existing controlled conflict response.

Cancellation is best-effort. Ollama HTTP work is cancelled with its task. A synchronous OS tool already running in a worker thread may finish physically, but its late result cannot complete the cancelled run or be written to session history.

Cancellation and timeout races use a first-terminal-outcome policy: whichever transition is accepted first wins, and every later terminal transition or output event is ignored or rejected. A validated cancellation request signals the execution task and atomically records `CANCELLING` then `CANCELLED`, including when cancellation arrives before the task starts. The 12,000-character Ollama stream ceiling is fail-closed; oversized output produces `FAILED`, and no partial response is committed to conversation history.

V0.6 has no embeddings, RAG, vector database, semantic search, autonomous memory extraction, conversation summarisation, skills, delegation, schedulers, or external agent framework.

## Project security model

- No recursive filesystem scan and no file-content access.
- Symlinks resolving outside `PROJECTS_ROOT` are ignored.
- API and tool requests use opaque project IDs, never caller-supplied paths.
- Ollama can propose only registered, schema-validated tool calls.
- Git runs as argument arrays with a short timeout; no shell is involved.
- `.env`, SSH keys, credentials, and arbitrary project files are never read or sent to Ollama.
- Session context is process-local, bounded, expires automatically, and is deleted on reset.
- Persistent memory is bounded SQLite data, contains no paths or transcripts, and is never authorization.

## Validation

```bash
npm test
npm run lint
npm run typecheck
npm run build
apps/api/.venv/bin/pytest apps/api
apps/api/.venv/bin/ruff check apps/api
```

See [docs/architecture.md](docs/architecture.md) for boundaries and extension guidance.
