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
- `GET /projects`: safe metadata and aggregate status for discovered projects.
- `GET /projects/{project_id}`: one project resolved through an opaque server ID.

The runtime flow is deliberately narrow:

```text
Next.js dashboard -> FastAPI /chat -> assistant orchestrator -> Ollama router
                                            |                    |
                                            v                    v
                                   approved project tool <- validated JSON
                                            |
                                            v
                                      grounded result -> Ollama final response
```

Ollama is never called from the browser. The backend selects the configured model, adds the registered JARVIS personality, applies request limits, and converts runtime failures into a controlled `503` response. Clients cannot choose arbitrary Ollama endpoints or models.

## Local-first boundaries

SQLite lives under the repository-local `data` directory by default and is excluded from source control. General settings use `JARVIS_` variables; Ollama and project discovery use the explicit `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `PROJECTS_ROOT` variables. Secrets must live only in ignored environment files or a future macOS keychain adapter.

The API is the intended boundary for persistence, model access, tools, and integrations. UI components should not reach Ollama, SQLite, or third-party services directly.

## Assistant and conversation boundaries

Assistant definitions live in `jarvis_api/assistants.py`, separate from transport and routes. The registry currently contains JARVIS and can accept another personality, such as FRIDAY, without changing the Ollama service. Codex is explicitly described as a separate future coding specialist and is never used as the conversational model.

Conversation display remains browser-local React state. Only the current message is sent to the API; refresh clears the transcript. There is no database history, memory, embedding, retrieval, or agent framework.

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
5. The backend executes the approved tool and gives its sanitised result to Ollama for a grounded final response.
6. Invalid routing executes nothing and returns a safe failure statement.

Approved tools are `list_projects`, `get_project_status`, `get_recent_project_activity`, and `open_project`. The launch tool supports only VS Code and Finder. Permission is derived from explicit original user wording, including the named project and application; the model cannot grant permission.

## Future extension points

- Add assistant/message tables behind a repository layer before persistent memory.
- Add bounded multi-turn context once conversation/session semantics are designed.
- Treat Codex as an explicit specialist tool, not the default conversation provider.
- Add integrations as isolated adapters with explicit permissions and credential storage.
- Introduce background jobs only when a real workload requires them.

Authentication, hosted infrastructure, long-term memory, voice, browser automation, agent frameworks, and external connectors are intentionally outside this milestone.
