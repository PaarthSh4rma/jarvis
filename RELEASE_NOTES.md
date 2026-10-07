# JARVIS V0.8.0

V0.8.0 introduces the Stark-style JARVIS command centre and its first durable,
local control-plane foundations:

- read-only Hermes health and capability readiness checks;
- durable Missions and Approvals with revision and validation safeguards;
- Mission and Approval interfaces that preserve human review;
- Codex and Claude worker contracts without worker execution or delegation;
- improved project, run, memory, and skills visibility and controls; and
- isolated offline behavior so unavailable Ollama or Hermes services do not
  disable deterministic JARVIS controls.

Mission readiness does not dispatch work. Resolving an Approval records the
human decision only and performs no action.

V0.8.0 does not include Hermes task execution, Codex or Claude delegation, the
Application Factory, calendar or email integration, or autonomous actions.
