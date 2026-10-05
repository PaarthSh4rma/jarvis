# Locally verified Hermes integration facts

Inspected 2026-10-04. Source paths below are relative to the installed
`~/.hermes/hermes-agent` checkout. No credential file was read.

- `gateway/platforms/api_server.py` implements an aiohttp `APIServerAdapter`.
  Defaults are `127.0.0.1:8642`; platform extras or `API_SERVER_HOST` /
  `API_SERVER_PORT` can override them. The local config has an `api_server`
  section, but inspection did not establish an effective listener override.
- `GET /health` (also `/v1/health`) is public and returns
  `{status: "ok", platform: "hermes-agent", version: <string>}`. Version is
  package metadata with a `dev` fallback. This is liveness, not worker readiness.
- `GET /v1/capabilities` requires Bearer authentication. Its identifying fields
  are `object: "hermes.api_server.capabilities"`, `platform: "hermes-agent"`.
  It includes `auth`, `runtime`, `features`, and an endpoint map. Features include
  boolean `run_submission`, `run_status`, `run_events_sse`, `run_stop`,
  `run_approval_response`, and `session_resources`. It does not supply version.
- `GET /health/detailed` is authenticated and contains runtime readiness and
  platform/process metadata. The JARVIS adapter will not expose that payload.
- The startup guard requires a usable `API_SERVER_KEY`. Protected handlers
  compare `Authorization: Bearer ...` with the configured/profile-scoped key.
  The no-key auth bypass in source is for test/manual wiring, not a production
  startup assumption. No key was read, changed, or copied.
- The source route tables expose session CRUD at `/api/sessions`, chat at
  `/api/sessions/{session_id}/chat`, streaming at its `/stream` suffix, and
  OpenAI-compatible `/v1/chat/completions` and `/v1/responses`.
- `gateway/platforms/api_server_runs.py` defines `POST /v1/runs` with `input`
  and optional session/model/context fields, returning a `run_id` and queued
  status. `GET /v1/runs/{run_id}` reads status; `/events` streams SSE;
  `POST /v1/runs/{run_id}/stop` requests cancellation.
- Run approval is `POST /v1/runs/{run_id}/approval`, with `choice` and optional
  `request_id`; choices include once/session/always/deny, with stricter room
  scope rules. This resolves Hermes execution waiters, unlike this sprint's
  local decision records. No bridge between these mechanisms is implemented.
- The API advertises a browser-control WebSocket at `/v1/browser-control/ws`;
  it uses registration tickets. It is not a general task-status WebSocket.
- Initial probes were blocked by sandbox networking; bounded unauthenticated GET
  probes repeated outside the sandbox still returned connection failures for both
  `/health` and `/v1/capabilities`. Effective
  running host/port and live version were therefore not established.

Execution test is skipped: a running authenticated API and a guaranteed
zero-paid-token, no-external-communication execution path were not established.
Only the two read-only endpoints above will be consumed by JARVIS.

## Final read-only gateway diagnosis

- `launchctl print` for `ai.hermes.gateway` reports the service running. Its
  parent and child Python processes both exist. The last recorded exit was
  75 (EX_TEMPFAIL); that is historical, not proof of a current startup failure.
- An unsandboxed listener check finds nothing on TCP port 8642, and neither
  process in the service tree has any TCP listener on another port.
- Unsandboxed connections to both `127.0.0.1:8642` and `[::1]:8642` are refused
  (errno 61). Authentication and endpoint routing have not been reached.
- The default runtime-state file identifies the live child PID, says running,
  and contains zero platform entries, including no API-server entry. This file
  is supporting evidence; the live socket/process checks establish the absence
  of a listener.
- The inspected `api_server` YAML section supplies `max_concurrent_runs: 10`;
  no host, port, or enabled override was present in that section.
- `gateway/config_env.py::_api_server` returns without enabling the adapter
  unless `API_SERVER_KEY` is usable. Its presence/value in the running service
  was deliberately not inspected. Missing/disabled adapter configuration is a
  plausible explanation, not a verified credential diagnosis.
- Bounded service-log tails had no API-server, missing-key startup-guard, or
  address-in-use matches. Raw logs, environment, and process arguments were not
  printed. This absence does not prove there were no earlier errors.

Conclusion: the service is running, but its HTTP API adapter is not listening;
this is not merely the earlier sandbox limitation. No evidence of another port
or IPv6-only listener was found. Exact configuration/root cause remains unverified.
An operator must separately check the supported adapter enablement and usable-key
configuration, and start/reload the API listener if appropriate. That requires
Hermes/service changes outside this pass; none were performed.
