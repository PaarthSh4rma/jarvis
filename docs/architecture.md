# Architecture

## Shape

JARVIS is a local-first monorepo with independently runnable surfaces:

- `apps/web`: Next.js App Router, TypeScript, and Tailwind CSS. The browser owns presentation and calls the local API through a small typed client.
- `apps/api`: FastAPI application with configuration, routing, and SQLite lifecycle split into separate modules.
- `scripts`: developer helpers as the project grows.
- `docs`: architectural decisions and contributor guidance.

The implemented cross-surface contracts are:

- `GET /health`: API identity/version, Ollama availability, and the server-configured model.
- `POST /chat`: one validated user message in, one JARVIS response out.
- `POST /runs`: create one opaque, conversation-owned execution run.
- `GET /runs/{run_id}/events`: consume ordered structured events over SSE.
- `POST /runs/{run_id}/cancel`: request idempotent, ownership-checked cancellation.
- `POST /conversations`: create an opaque short-term session.
- `DELETE /conversations/{conversation_id}`: discard a session and its context.
- `GET /projects`: safe metadata and aggregate status for discovered projects.
- `GET /projects/{project_id}`: one project resolved through an opaque server ID.
- `GET /skills`: safe bounded metadata for repository-authored skills.
- `GET/POST /memory`: list or add bounded persistent memory.
- `PATCH/DELETE /memory/{memory_id}`: update or delete one opaque memory entry.

The runtime flow is deliberately narrow. `/chat` remains the non-streaming compatibility path:

```text
Next.js dashboard -> FastAPI run coordinator -> bounded run store -> SSE events
                                      |                    ^
                                      v                    |
                              in-memory session -> assistant orchestrator
                                            ^                  |
                                            |                  v
                                     SQLite memory -> bounded untrusted data context
                                      trusted skill registry -> bounded selection index
                                                               -> Ollama routers
                                            |                    |
                                            v                    v
                                   approved project tool <- validated JSON
                                            |
                                            v
                                      grounded result -> deterministic final formatter
```

Ollama is never called from the browser. The backend selects the configured model, adds the registered JARVIS personality, applies request limits, and converts runtime failures into a controlled `503` response. Clients cannot choose arbitrary Ollama endpoints or models.

## Local-first boundaries

SQLite lives under the repository-local `data` directory by default and is excluded from source control. It stores only explicit persistent memory, not chat transcripts, runs, or skill history. General settings use `JARVIS_` variables; Ollama, project discovery, and skill discovery use the explicit `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `PROJECTS_ROOT`, and `SKILLS_ROOT` variables. Secrets must live only in ignored environment files or a future macOS keychain adapter.

The API is the intended boundary for persistence, model access, tools, and integrations. UI components should not reach Ollama, SQLite, or third-party services directly.

Project discovery is never persisted in browser storage. The dashboard maintains explicit loading, available, and unavailable states, fetches `/projects` on each mount, and can retry a failed request. A successful response atomically replaces stale project data and clears the unavailable state independently of conversation restoration.

## Isolated demo mode

`JARVIS_DEMO_MODE=true` is an explicit local presentation mode. The accompanying setup
script owns only ignored `.demo/` state and creates three ordinary Git repositories with
fixed names, commits, branches, and clean working trees. `DemoProjectService` changes only
their presentation order; metadata and status still come from `ProjectService` and Git.
Opaque identifiers, root containment, tool schemas, run ownership, and trusted observation
rules remain in force.

The demo accepts an explicit bare `open` instruction as permission to use the existing
allowlisted VS Code target, only for a project already resolved from trusted context. With
demo mode disabled, the existing destination clarification remains mandatory. The health
contract exposes the mode so the frontend can use a compact recording layout and permit
the deterministic demo commands even if Ollama is offline; it continues to display the
real Ollama status, and non-deterministic conversation still fails safely without Ollama.

## Assistant and conversation boundaries

Assistant definitions live in `jarvis_api/assistants.py`, separate from transport and routes. The registry currently contains JARVIS and can accept another personality, such as FRIDAY, without changing the Ollama service. Codex is explicitly described as a separate future coding specialist and is never used as the conversational model.

The visible transcript remains browser-local. The opaque active session UUID is retained in `localStorage`; a bounded snapshot of completed UI exchanges is retained only in the current tab's `sessionStorage` so refresh does not erase completed work. The snapshot is capped at 24 messages and 12,000 characters, is keyed to the session UUID, excludes partial and unsuccessful runs, and is deleted by `NEW SESSION` or an invalid backend session. SQLite never stores transcripts.

## Short-term session lifecycle

`ConversationStore` is an in-process, lock-protected store keyed by UUID. A session is created lazily by the frontend, required on every chat request, and removed by `NEW SESSION`, API restart, or expiry. Unknown sessions return `404`, expired sessions return `410`, and malformed identifiers return `422`; the frontend clears stale local IDs without crashing.

Defaults are a 30-minute inactivity TTL, 12 user turns, and 12,000 total characters. Trimming removes the oldest complete turn deterministically until both bounds hold. A single current turn is retained even when it alone exceeds the character budget. There is no session summarisation or transcript persistence.

Each turn separates user text, assistant text, and an optional compact trusted tool observation. Prompt messages likewise keep personality, dialogue history, routing instructions, current user input, and current trusted tool output as distinct roles/messages rather than one uncontrolled string.

Pronouns and ordinals are resolved only from recent trusted observations. A unique `project` observation resolves `it`; list observations can resolve `first`, `second`, or `third`. Dirty-project follow-ups consider only entries whose authoritative `is_dirty` field is `true`. Missing or multiple referents produce a clarification before Ollama or tools run.

Reference resolution yields an opaque project ID from trusted backend observations or the current discovered-project index. An explicitly named current project takes precedence over a stale conversational referent. A partial explicit descriptor that matches multiple projects clarifies instead of reusing stale context. The normal Pydantic tool schema validates the resolved ID, and the registry resolves it beneath `PROJECTS_ROOT`. Conversation context grants no permissions. An ordinal launch additionally requires explicit current-turn wording naming VS Code or Finder; prior conversation cannot authorise an external action.

## Persistent memory

`MemoryStore` is a small SQLAlchemy Core repository over one SQLite `memories` table. Each row has an opaque UUID, `user` or `project` scope, optional opaque project ID, content, and created/updated timestamps. Repository initialization is idempotent and storage survives service re-instantiation. The default database file and its WAL/SHM companions are ignored by Git.

The bounds are 50 user entries, 25 entries per project, 500 characters per entry, and 2,000 total memory-content characters injected into a prompt. Selection is ordered deterministically by update time then ID; resolved project entries are selected before user entries. Unrelated project entries are never selected. Memory does not consume or weaken the separate 12,000-character short-term session budget.

Chat mutation is deliberately deterministic and requires explicit `remember`, `save this`, `keep this in mind`, `forget`, or `remove memory` language. There is no automatic extraction. REST mutations and chat mutations both pass through the repository's validation and bounds. Common credential/secret markers are rejected. Ambiguous deletion changes nothing.

Ordinary conversation never enters the project-tool router merely because the router exists. Only requests with a project/tool semantic candidate may ask Ollama for a structured project call; unmatched preference, memory-retrieval, and social questions go directly to conversational chat with bounded memory. Consequently, project validation failures are reported only for genuine project-operation attempts. An open request that resolves a project but omits VS Code or Finder asks for the destination and records only the trusted project referent—never launch permission.

Prompt construction keeps personality, bounded memory data, session history, routing, current input, and trusted observations logically separate. Memory sent to Ollama omits memory IDs and project IDs and is labelled untrusted contextual data, never an instruction or authorization. Memory is not sent into tool routing. The enforced contextual precedence is:

```text
LIVE TRUSTED OBSERVATION > EXPLICIT CURRENT USER STATEMENT > PERSISTED MEMORY
> SELECTED SKILL PROCEDURE > MODEL INFERENCE
```

Authorization is separate from contextual precedence. Neither memory nor a selected skill can grant tool permission, weaken project/path validation, or override current Git state.

## Declarative skills

V0.7 keeps knowledge, procedure, and executable capability distinct:

```text
                    JARVIS
                  Ollama brain
                       |
        +--------------+--------------+
        |              |              |
      MEMORY          SKILLS         TOOLS
   what it knows   how to do it   what it can do
        |              |              |
        +--------------+--------------+
                       |
                 ORCHESTRATOR
                       |
                 V0.6 RUN TIME
                       |
                VALIDATED ACTIONS
```

`SkillRegistry` discovers only immediate child directories beneath canonical `SKILLS_ROOT`, resolving every directory and `SKILL.md` back beneath that root. Definitions have strict `name`, `description`, `scope`, and integer `version` frontmatter followed by Markdown procedure text. Names are lowercase ASCII words separated by hyphens. V0.7 supports only `project` scope; user scope is deferred until it has a concrete validated capability. Duplicate names, additional or missing metadata, invalid scope/version/encoding, escaping symlinks, oversized content, and excessive registry counts reject the registry.

Bounds are 12 skills, 12,288 bytes per file, 64 name characters, 180 description characters, 8,000 procedure characters, a 3,000-character compact selection index, and exactly one selected skill per run. `GET /skills` returns only name, description, scope, and version—never procedure or canonical path. The dashboard re-fetches this authoritative index on mount and exposes loading, unavailable, and retry states.

Selection uses progressive disclosure. Explicit `Use <safe-name>` and `Run <safe-name>` requests resolve directly against the registry. A natural procedural request with one resolved project may ask Ollama to choose an exact name from the compact metadata index. Output shape, name syntax, and registry membership are revalidated; malformed JSON, lists, unknown names, tool-shaped data, and path-like values select nothing. Ordinary conversation does not invoke the selector merely because skills exist. A bounded `How about RaceBrain?` follow-up may reuse the previous skill only after normal project resolution selects the newly named project.

Only the selected procedure is added in a separate system context message. It is labelled as trusted repository-authored procedural guidance, never authorization or factual authority. Unrelated procedures are absent. Memory remains separate untrusted data; skill text cannot turn it into an instruction.

The starter skills are `project-health-check` and `project-summary`. Both are project-scoped, read-only, and map through backend code to the existing validated `get_project_status` tool. Procedure prose is never parsed into function calls, so text requesting shell access, arbitrary paths, application launch, memory mutation, or unknown tools gains no capability. `inspect-project` is omitted because current tools would make it functionally redundant.

Skill execution remains inside `RunExecutor`; there is no competing state machine. Bounded `skill.selected`, `skill.started`, `skill.completed`, and `skill.failed` events carry only a registered name and safe status. Cancellation or timeout removes authority to advance, emit late output, write session history, or complete successfully. Skills may receive already-bounded memory context, but never write memory automatically or store execution history.

## Execution lifecycle

`RunStore` centrally enforces `QUEUED -> RUNNING`, optional `WAITING_FOR_TOOL`, and exactly one of `COMPLETED`, `FAILED`, `CANCELLED`, or `TIMED_OUT`; cancellation passes through `CANCELLING`. Illegal transitions fail closed. One run may be active per conversation. Runs are process-local and bounded to 100 entries, 200 retained events each, and a 15-minute terminal TTL by default.

The frontend creates a run and reads ordered SSE frames. Events contain state, bounded assistant text deltas, safe tool/skill names, and human-readable action descriptions—never raw arguments, paths, prompts, procedures, memory rows, secrets, or model reasoning. Ollama's NDJSON stream is converted into `assistant.delta` events with a 12,000-character output ceiling. The final assembled answer is appended as one conversation turn only after successful completion.

Overall runs and individual tool calls have separate configurable deadlines. Cancellation removes the run's authority to commit a result; late model or synchronous worker results cannot resurrect it. SSE supports a numeric cursor while events remain retained. Browser refresh deliberately detaches the active SSE request and does not persist run identifiers or partial output. The remounted UI restores only the matching session's bounded completed-message snapshot and returns to idle; the backend run continues independently to one terminal state.

Terminal races are serialized by the run store. The first valid terminal transition wins; subsequent cancellation is idempotent and any attempted state mutation is rejected centrally. Assistant deltas and tool progress are accepted only while the run is in the corresponding active state. Malformed or oversized Ollama streams fail closed and never create a successful conversation turn.

## Project discovery

`ProjectService` resolves `PROJECTS_ROOT` once and considers only immediate child directories with recognised project markers. Every candidate is resolved to its canonical path and must remain beneath the configured root; escaping symlinks are discarded. Stable opaque IDs are hashes of canonical internal paths. Paths are retained for backend inspection and launch operations but omitted from API and model-facing results.

Metadata includes Git presence, branch, dirty state, last commit subject/timestamp, and technology hints inferred only from marker filenames. Project contents are not exposed.

The Git command allowlist is implemented as fixed subprocess argument arrays:

```text
git -C <validated-project> branch --show-current
git -C <validated-project> status --porcelain
git -C <validated-project> log -1 --format=%s
git -C <validated-project> log -1 --format=%cI
```

Calls have short timeouts, capture output, and never use `shell=True`. A failed status check yields unknown status rather than incorrectly reporting a clean repository.

## Tool execution lifecycle

1. FastAPI constructs an assistant orchestrator with the configured Ollama and project services.
2. Ollama receives tool descriptions, JSON argument schemas, and project names/opaque IDs—never paths.
3. Ollama returns one strict JSON routing decision or no tool.
4. The registry rejects unknown tools, extra or malformed arguments, unknown IDs, and unauthorised actions.
5. The backend executes the approved tool and deterministically renders its sanitised result. Explicit tool fields are authoritative; unrelated metadata cannot override them, and opaque IDs are not exposed in prose.
6. Invalid routing executes nothing and returns a safe failure statement.

Approved tools are `list_projects`, `get_project_status`, `get_recent_project_activity`, and `open_project`. The launch tool supports only VS Code and Finder. Permission is derived from explicit original user wording, including the named project and application; the model cannot grant permission.

## Future extension points

- Persist sessions only if a later milestone establishes an explicit local transcript-retention policy.
- Treat Codex as an explicit specialist tool, not the default conversation provider.
- Add integrations as isolated adapters with explicit permissions and credential storage.
- Introduce background jobs only when a real workload requires them.
- Consider skill composition only after a later milestone defines bounded sequencing and authority rules.

Automatic or model-authored skill creation/editing, marketplaces, arbitrary shell/Python execution, Codex delegation, MCP, authentication, hosted infrastructure, transcript history, semantic memory, voice, browser automation, schedulers, agent frameworks, and external connectors are intentionally outside this milestone.
