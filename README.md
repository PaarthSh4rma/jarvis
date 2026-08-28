# JARVIS

A local-first personal assistant and developer command centre. V0.3 adds bounded awareness of local software projects while preserving Ollama-only conversation. JARVIS can inspect approved project metadata and Git status without receiving unrestricted filesystem or shell access.

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

## Project security model

- No recursive filesystem scan and no file-content access.
- Symlinks resolving outside `PROJECTS_ROOT` are ignored.
- API and tool requests use opaque project IDs, never caller-supplied paths.
- Ollama can propose only registered, schema-validated tool calls.
- Git runs as argument arrays with a short timeout; no shell is involved.
- `.env`, SSH keys, credentials, and arbitrary project files are never read or sent to Ollama.

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
