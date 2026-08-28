# Architecture

## Shape

JARVIS is a local-first monorepo with independently runnable surfaces:

- `apps/web`: Next.js App Router, TypeScript, and Tailwind CSS. The browser owns presentation and calls the local API through a small typed client.
- `apps/api`: FastAPI application with configuration, routing, and SQLite lifecycle split into separate modules.
- `scripts`: developer helpers as the project grows.
- `docs`: architectural decisions and contributor guidance.

The only implemented cross-surface contract is `GET /health`. The frontend treats any invalid or unreachable response as offline. No command text is transmitted yet.

## Local-first boundaries

SQLite lives under the repository-local `data` directory by default and is excluded from source control. Configuration comes from environment variables prefixed with `JARVIS_`; secrets must live only in ignored environment files or a future macOS keychain adapter.

The API is the intended boundary for persistence, model access, tools, and integrations. UI components should not reach Ollama, SQLite, or third-party services directly.

## Future extension points

- Add assistant/message tables behind a repository layer before persistent memory.
- Add an Ollama adapter behind an application service; keep model selection outside route handlers.
- Treat Codex as an explicit specialist tool, not the default conversation provider.
- Add integrations as isolated adapters with explicit permissions and credential storage.
- Introduce background jobs only when a real workload requires them.

Authentication, hosted infrastructure, voice, browser automation, agent frameworks, and external connectors are intentionally outside this milestone.
