# JARVIS

A local-first personal assistant and developer command-centre foundation. This milestone provides a polished dashboard, a FastAPI health service, and SQLite-ready backend infrastructure. It intentionally does **not** include an LLM, command execution, authentication, or external integrations.

## Prerequisites

- macOS (primary development environment)
- Node.js 20+ and npm 10+
- Python 3.10+

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

## Run locally

Use two terminals from the repository root:

```bash
apps/api/.venv/bin/uvicorn jarvis_api.main:app --app-dir apps/api --reload --port 8000
```

```bash
npm run dev:web
```

Open [http://localhost:3000](http://localhost:3000). The dashboard checks [http://localhost:8000/health](http://localhost:8000/health) and updates the JARVIS status automatically.

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
