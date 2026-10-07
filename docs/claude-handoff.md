# Claude Review Handoff

## Goal

Prepare JARVIS for Hermes orchestration and later Application Factory work while
retaining the V0.7 chat/runtime boundaries. This sprint does not build the Factory
or execute missions. Changes are uncommitted on `feat/hermes-foundation`.

## Current Architecture

JARVIS owns UI, durable missions, and local approval decisions. FastAPI exposes
dedicated deterministic APIs. Hermes is an independent read-only status adapter
today; orchestration/scheduling/delegation remain its intended future ownership.
Codex and Claude are future implementation/review workers with data contracts
only. Paarth OS is the intended policy, project-registry, and verified-career
authority, but is not connected. Existing ProjectService remains authoritative
for currently supplied project IDs.

## What Codex Changed

- `integrations/hermes.py`: loopback-only GET client for verified health and
  capabilities; strict projected payloads, size/deadline limits, safe failures.
- `missions.py`: strict contracts, local SQLite repository, revision checks.
- `approvals.py`: internal creation and atomic, idempotent local resolution.
- `agents.py`: bounded worker task/result contracts without implementations.
- `routes/`: focused integration, mission, and approval routers.
- `main.py` / `config.py`: minimal dependency wiring and additive initialization.
- `hermes-status.tsx`, API helpers, dashboard mount: independent read-only status.
- Backend/frontend tests: adapters, persistence, conflicts, safety, UI/offline.
- Runtime metadata/docs: Python 3.11 minimum; Node 22 CI guidance and Node 26
  test-only invocation guidance. No dependency upgrades.

The hardening pass reproduced SQLite integer-binding overflows and added request
bounds. It also enabled foreign keys on every application SQLite connection and
made resolution reject legacy orphan approvals, with rollback coverage. New tests
exercise these cases, result/state forgery, slow streamed bodies, huge responses,
hostile extra fields, IPv6, and proxy/redirect isolation. Final validation:
223 backend tests and 44 frontend tests passed; frontend lint, standalone
typecheck, production build, Ruff, and `git diff --check` passed. All 15 new files
were also checked for whitespace errors. Frontend tests used
`NODE_OPTIONS=--no-experimental-webstorage`. One existing Starlette/httpx
TestClient deprecation warning remains.

Self-review found two MEDIUM issues fixed locally: out-of-range SQLite integer
bindings could produce server errors; unenforced references could permit orphan
approval decisions. No unresolved BLOCKER/HIGH issue was identified within the
current local, non-executing scope. Migration/versioning remains a LOW limitation
for additive tables. Missing authenticated identity and exact-action binding are
mandatory gates before any future executable approvals, not claims of safety
for such execution today. No abstraction rewrite was justified by this review.

Live diagnosis found a running launchd parent/child pair but no TCP listener on
either process; IPv4 and IPv6 port 8642 refuse connections outside the sandbox.
Runtime state has no platform adapters. Installed source gates the API adapter
on a usable key, but credentials were not inspected. Exact enablement failure
remains unverified. See the integration note for evidence and operator next steps.

## Decisions Made

- Only Hermes `/health` and `/v1/capabilities` are called; no CLI fallback.
- Defaults follow installed source: loopback port 8642. No live server was
  reachable there during inspection. Credential files were not read.
- Capabilities may be UNKNOWN/authentication_required while health is ONLINE.
  Only a configured JARVIS backend secret may authenticate capability reads.
- Mission and approval persistence use separate tables in existing SQLite;
  neither depends on ephemeral RunStore or memory.
- Mission create always yields DRAFT. Public updates permit DRAFT ↔ READY and
  cancellation only, with `expected_revision`. Execution states are reserved.
- Approval creation is service-level only; resolution cannot dispatch anything,
  cannot change mission status, and cannot overwrite a prior different decision.
- Public integer bounds match SQLite. The application engine enables foreign
  keys for every SQLite connection; resolution fails closed for legacy orphans.
- No mission/approval UI, worker, generic executor, scheduling, or Factory feature
  was added. The optional Hermes execution experiment was skipped.

## Unresolved Questions

- What is the supported live gateway endpoint and credential provisioning model?
- How should human identity and action/revision-bound approval work before any
  real execution? Current requested_by is descriptive, not authenticated.
- Should mission edits invalidate or supersede prior decision records? They
  currently cannot authorize execution, so this is deliberately not wired.
- Which transitions/results should only Hermes reconciliation be allowed to write?
- When should additive table initialization become versioned migrations?
- What durable idempotency/recovery contract is needed across JARVIS/Hermes restarts?
- Are the bounded worker data contracts useful now, or still too early?

## Security Boundaries

Do not turn a mission state or APPROVED row into executable permission. Before
execution, bind a decision to an immutable action identifier, canonical action
parameters (or their hash), mission revision, requested worker, and permission
scope, and authenticate the human decision maker. Define expiry/revocation and
atomic one-time consumption before dispatch. None of these executable-grant
bindings exist today: action_type, summary, and risk_context are decision context
only. Mission edits/cancellation do not silently dispatch or revoke actions;
there are no actions to dispatch, and existing decisions remain historical records.
The existing local API has no authentication; keep it on loopback. CORS/UUIDs
are not identity. Never relay raw Hermes config, responses, or credentials.
Hermes input cannot add tools or permissions. Never automatically submit jobs,
send messages, spend money, invent career evidence, or execute arbitrary model
output. This sprint does not modify Hermes, credentials, launchd, or Git history.

## Requested Claude Review

Please independently inspect:

- Architecture boundaries and unnecessary abstractions.
- Security issues, including the distinction between decisions and permissions.
- Mission model and allowed transitions.
- Approval model, immutability, stale decisions, and concurrency behavior.
- Hermes adapter validation, failure handling, auth isolation, and network bounds.
- Concurrency, cancellation, restart, and reconciliation concerns for future work.
- SQLite persistence choices and migration needs.
- Testing gaps, including real gateway compatibility and unsupported environments.
- Whether this foundation supports Application Factory cleanly without coupling
  acquisition providers or worker execution into domain records.

Please challenge these choices and report evidence for your conclusions.
Independently determine whether the foundation should be **ACCEPTED**,
**ACCEPTED WITH CHANGES**, or **REWORKED**. Do not assume that passing tests or
this handoff establishes architectural or security approval.
