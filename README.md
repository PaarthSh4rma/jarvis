# JARVIS

A local-first personal assistant and developer command centre. V0.8.0 adds the Stark-style command centre, read-only Hermes readiness, and durable Mission and Approval controls while preserving local-first safety boundaries. See the [V0.8.0 release notes](RELEASE_NOTES.md).

## Prerequisites

- macOS (primary development environment)
- Node.js 22 (the CI baseline) and npm 10+
- Python 3.11+ (`StrEnum` and `datetime.UTC` are used)
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

No secrets are required for local chat, mission records, or public Hermes health.
Hermes capability discovery optionally needs a backend-only gateway credential.
Environment files are ignored by Git.

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
SKILLS_ROOT=./skills
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

## V0.8.0 command centre and control-plane foundation

The Systems section now checks Hermes independently of Ollama and chat. It shows
gateway liveness, verified version, a limited advertised-capability summary, and
the last successful health check. Checking runs on mount and on explicit retry;
there is no background scheduler. Offline Hermes does not prevent JARVIS loading.

The backend only calls `GET /health` and `GET /v1/capabilities` on Hermes.
Configure `JARVIS_HERMES_BASE_URL` (default `http://127.0.0.1:8642`). Only HTTP
loopback origins are accepted; localhost is pinned to 127.0.0.1, redirects and
environment proxies are disabled. Checks have a 1-second connect timeout,
2-second read timeout, 4-second total deadline, and 64 KiB response limit.

If authenticated capability discovery is desired, an operator may separately
supply `JARVIS_HERMES_API_KEY` to the JARVIS backend environment. This sprint does
not read Hermes credential files or provision/copy credentials. The key is never
returned to the frontend. Without access to the capability endpoint, the UI
can still display verified public health; capability state is `UNKNOWN` on
401/403. `ONLINE` means the relevant endpoint returned a validated response,
not that workers are configured or ready to execute.

Read-only JARVIS endpoints:

- `GET /integrations/hermes/health`
- `GET /integrations/hermes/capabilities`

Both return `state`, `version`, `capabilities`, `checked_at`,
`last_successful_check`, and a fixed safe `reason`. Network/timeouts return
`OFFLINE`; invalid responses or HTTP failures return `DEGRADED`; denied
authentication returns `UNKNOWN`. Upstream bodies/configuration are not relayed.
Last-success timestamps are process-local and tracked separately per endpoint.

### Local missions and approvals

Mission records live in a dedicated SQLite `missions` table, separate from
ephemeral runs and memory. No mission operation calls a model or dispatches work.

- `POST /missions`: `type`, `title`, `goal`, optional `project_id`, `context`,
  `requested_by` (default `local-user`). Creates `DRAFT` with revision 1.
- `GET /missions` and `GET /missions/{id}`: durable local records.
- `PATCH /missions/{id}`: requires `expected_revision`; editable fields are
  title, goal, project reference, context, and status.

Types are CODE_CHANGE, PROJECT_REVIEW, JOB_APPLICATION, RESEARCH,
INTERVIEW_PREP, MONEY_EXPERIMENT, and ADMIN. Status contracts also reserve RUNNING,
WAITING_FOR_APPROVAL, COMPLETED, and FAILED for later execution integration.
Current CRUD allows DRAFT ↔ READY and either → CANCELLED. Cancellation is terminal.
READY does not run anything. Existing project IDs are checked when supplied;
missions without a project do not invoke discovery. Execution IDs and result/
failure summaries are reserved output fields, not accepted from public mutations.
Concurrent stale updates return 409. `requested_by` is descriptive local metadata,
not authenticated identity.

Approval records live in a separate `approvals` table. Internal code can use
`ApprovalStore.create(ApprovalCreate(...))` with an existing mission UUID,
action type, summary, and risk context. There is no public creation endpoint.

- `GET /approvals` (optional `mission_id`) and `GET /approvals/{id}`.
- `POST /approvals/{id}/resolve`: `status` APPROVED/REJECTED/CANCELLED and optional
  `resolution_note`. PENDING is the initial internal creation state.

Resolution changes only the decision row. It does not change the mission, contact
Hermes, invoke a tool, or perform the proposed action. Exact retries are idempotent;
conflicting later decisions return 409. Mission and approval lists accept `limit`
(default 50, max 100) and `offset`. Unknown mutation fields are rejected.
Revisions and offsets have SQLite-compatible integer bounds. Database connections
enable foreign-key enforcement; legacy orphan approvals cannot be resolved.
The command centre includes Mission and Approval panels for these durable records.
Neither panel dispatches work or performs an approved action.

### Ownership and security

JARVIS owns the human interface, durable records, and local decision records.
Hermes is the intended future orchestration/scheduling/delegation boundary.
Codex and Claude have data contracts only; no worker implementation exists.
Paarth OS remains the intended authority for policies, project registry, career
evidence, and spending rules; no Paarth OS connector was added, and current
project validation still uses the existing local ProjectService.

Keep the API bound to loopback. Existing JARVIS has no user authentication;
CORS and opaque UUIDs are not an identity or authorization system. These approval
records are not yet an authorization gateway for execution. Future execution must
bind approval to an exact action and mission revision, authenticate the decision
maker, and enforce permission scope independently of model text.

Not implemented: mission execution, Hermes approval forwarding, Codex/Claude
workers, scheduling, Daily Brief, Application Factory, career evidence ingestion,
Crawl4AI, submission, email sending, paid API access, or public deployment.

See [verified Hermes facts](docs/hermes-integration-notes.md),
[architecture](docs/architecture.md), and [Claude handoff](docs/claude-handoff.md).

### Local test runtime

Use Node 22 to match CI. On an existing Node 26 installation, Vitest/jsdom can
encounter Node's experimental Web Storage globals. Run
`NODE_OPTIONS=--no-experimental-webstorage npm test` in that environment.
No production-code workaround or dependency upgrade is required. Backend CI
uses Python 3.11; the package metadata now reflects the existing minimum.

## Record the trusted-reference demo

The public demo fixture is opt-in and isolated under ignored `.demo/` state. It creates
three real, clean Git repositories—RaceBrain, ExoHunter, and ClientOps Copilot—and sends
them through the normal project discovery, trusted-observation, reference-resolution,
tool-validation, and run-event paths. Demo mode never replaces assistant text in the
frontend and never changes behavior when `JARVIS_DEMO_MODE` is false.

For a manual recording, run these in separate terminals:

```bash
npm run demo:setup
npm run demo:api
```

```bash
npm run demo:web
```

Open [http://localhost:3100](http://localhost:3100), start a new session, and enter the
four prompts shown below. Demo mode treats an explicit bare `open` request as an approved
open in VS Code for the isolated fixture; normal mode still requires the user to name VS
Code or Finder.

```text
what projects am I working on?
open the second one
is it clean?
open the other one
```

To run the same flow in Playwright and save a 1280×720 WebM recording:

```bash
npx playwright install chromium  # first run only
npm run demo:record
```

Recordings are written beneath `demo-output/playwright/`, which is ignored by Git.

The project index is live backend state: the dashboard requests `/projects` on every mount or refresh and never treats browser storage as its source of truth. A temporary failure shows `PROJECT INDEX UNAVAILABLE`; use `RETRY PROJECT INDEX` to fetch it again without changing the conversation session or restored transcript.

If Ollama is stopped or the model is missing, the API remains healthy and reports the conversational runtime as offline. Chat requests return a controlled error rather than crashing the application.

Project-aware examples:

- `What projects do I have?`
- `Which projects have uncommitted changes?`
- `What branch is jarvis on?`
- `Open jarvis in VS Code.`
- `Sanity check jarvis.`
- `Use project-summary on jarvis.`

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

Memory is contextual data, not authority. Contextual precedence is `LIVE TRUSTED OBSERVATION > EXPLICIT CURRENT USER STATEMENT > PERSISTED MEMORY > SELECTED SKILL PROCEDURE > MODEL INFERENCE`. Stored text cannot grant tool permission, change configured roots, override path validation, or supersede a current Git observation. Memory is clearly labelled as untrusted data in the model context, including text that resembles instructions. Entries containing common credential markers such as passwords, API keys, access tokens, secrets, or private keys are rejected; memory is not a secret store.

### Execution runtime

The dashboard starts a run with `POST /runs`, then reads structured events from `GET /runs/{run_id}/events` using Server-Sent Events. Assistant text is assembled from `assistant.delta` events and committed to short-term session history only once the run completes. `POST /runs/{run_id}/cancel` is ownership-checked by conversation ID and is safe to repeat. The existing `POST /chat` contract remains available for compatibility.

Only one run may be active per conversation; different conversations can run independently. Overall execution defaults to 90 seconds and each approved tool to 15 seconds. The in-memory store retains at most 100 runs, 200 events per run, and terminal runs for 15 minutes. A refresh detaches the browser from its current stream, restores the same conversation identity and previously completed tab-local transcript, and clears only uncommitted activity. The backend still reaches a terminal state. V0.6 does not automatically reconcile that detached result into the UI; submitting again while it remains active receives the existing controlled conflict response.

Cancellation is best-effort. Ollama HTTP work is cancelled with its task. A synchronous OS tool already running in a worker thread may finish physically, but its late result cannot complete the cancelled run or be written to session history.

Cancellation and timeout races use a first-terminal-outcome policy: whichever transition is accepted first wins, and every later terminal transition or output event is ignored or rejected. A validated cancellation request signals the execution task and atomically records `CANCELLING` then `CANCELLED`, including when cancellation arrives before the task starts. The 12,000-character Ollama stream ceiling is fail-closed; oversized output produces `FAILED`, and no partial response is committed to conversation history.

### Declarative skills

A skill is repository-authored procedural guidance: it describes how JARVIS should approach a reusable task. It is not a tool, permission, executable file, autonomous agent, persistent memory, or hidden authority. V0.7 skills cannot run shell or Python, select arbitrary paths, create other skills, write memory automatically, or bypass validated tools.

Skills live beneath the configured trusted `SKILLS_ROOT` as one `SKILL.md` per directory. The small frontmatter schema is:

```markdown
---
name: project-health-check
description: Assess a project's current development health without modifying it.
scope: project
version: 1
---

# Project Health Check

Bounded procedural guidance follows here.
```

The registry accepts lowercase ASCII names containing digits and internal hyphens, project scope, versions 1–999, descriptions up to 180 characters, and procedures up to 8,000 characters. V0.7 deliberately supports only project-scoped skills; a later milestone may define user-scoped procedures when they have a concrete validated capability. The registry reads at most 12 skills, 12,288 bytes each, from immediate trusted-root child directories. Duplicate names, malformed metadata, invalid UTF-8, and canonical or symlink escapes fail closed. The compact selection index is capped at 3,000 characters, and only one skill may be selected per run.

Explicit invocation such as `Use project-health-check on JARVIS` resolves the exact registered name deterministically. Natural procedural requests use Ollama only to choose from the compact safe metadata index; the backend revalidates the answer and rejects invented names, paths, malformed JSON, and multiple selections. Ordinary conversation does not enter selection unless it contains a bounded procedural intent and an already-resolved project.

Progressive disclosure keeps every full procedure out of the general prompt. Only the selected procedure is added as a separately labelled context layer after selection. Project-scoped skills then resolve exactly one opaque project ID and use the existing `get_project_status` tool. Skill text never chooses executable functions. The initial registry contains `project-health-check` and `project-summary`; `inspect-project` was omitted because the existing read-only capability would make it indistinguishable from these two.

The dashboard fetches safe skill metadata from `GET /skills` on every mount. It exposes loading, available, unavailable, and retry states without storing the registry as browser authority. Runs may emit bounded `skill.selected`, `skill.started`, `skill.completed`, and `skill.failed` events; procedure text, paths, prompts, and tool arguments never enter SSE.

Skills inherit the existing one-run-per-conversation, cancellation, timeout, first-terminal-state, and late-result rules. They can receive bounded memory context, but neither skill text nor memory can authorise an action or create persistent memory. Context precedence is `LIVE TRUSTED OBSERVATION > EXPLICIT CURRENT USER STATEMENT > PERSISTED MEMORY > SELECTED SKILL PROCEDURE > MODEL INFERENCE`; tool authorization remains a separate backend decision.

Known V0.7 limitations: skills are local and repository-authored, only one skill is selected per run, both starter skills are project-scoped and read-only, natural selection depends on the configured local Ollama model, and detached active runs are not resumed after refresh. There is no composition, automatic creation/editing, marketplace, execution history, semantic search, Codex delegation, MCP, browser automation, scheduler, or voice support.

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
