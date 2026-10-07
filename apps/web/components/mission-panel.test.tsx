import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MissionPanel } from "./mission-panel";

const mission = {
  id: "11111111-1111-4111-8111-111111111111",
  type: "PROJECT_REVIEW",
  title: "Review JARVIS",
  goal: "Inspect the current project state.",
  project_id: "aabbccddeeff0011",
  context: "Read-only assessment.",
  requested_by: "local-user",
  status: "DRAFT",
  created_at: "2026-10-07T00:00:00Z",
  updated_at: "2026-10-07T00:00:00Z",
  revision: 1,
  external_execution_id: null,
  result_summary: null,
  failure_summary: null,
};
const projects = [{ id: "aabbccddeeff0011", name: "JARVIS", is_git_repository: true, branch: "main", is_dirty: false, latest_commit_message: "Stable", latest_commit_timestamp: "2026-10-07T00:00:00Z", technologies: ["Python"] }];
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("lists and inspects durable mission records", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(reply(url.endsWith(mission.id) ? mission : [mission]))));
  render(<MissionPanel projects={projects} />);

  expect(await screen.findByText("Review JARVIS")).toBeInTheDocument();
  expect(screen.getByText("1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "View mission Review JARVIS" }));
  expect(await screen.findByLabelText("Mission details")).toHaveTextContent("Inspect the current project state.");
  expect(screen.getByLabelText("Mission details")).toHaveTextContent("JARVIS");
  expect(screen.queryByRole("button", { name: /run|execute/i })).not.toBeInTheDocument();
});

it("creates a mission through the backend authority", async () => {
  const created = { ...mission, title: "Architecture review", goal: "Review module boundaries.", project_id: null };
  const fetchMock = vi.fn((url: string, options?: RequestInit) => Promise.resolve(
    options?.method === "POST" ? reply(created, 201) : reply([]),
  ));
  vi.stubGlobal("fetch", fetchMock);
  render(<MissionPanel projects={projects} />);

  await screen.findByText("NO MISSION RECORDS");
  fireEvent.click(screen.getByRole("button", { name: "CREATE MISSION" }));
  fireEvent.change(screen.getByLabelText("Mission type"), { target: { value: "CODE_CHANGE" } });
  fireEvent.change(screen.getByLabelText("Mission title"), { target: { value: "Architecture review" } });
  fireEvent.change(screen.getByLabelText("Mission goal"), { target: { value: "Review module boundaries." } });
  fireEvent.click(screen.getByRole("button", { name: "SAVE MISSION" }));

  expect(await screen.findByLabelText("Mission details")).toHaveTextContent("Architecture review");
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/missions", expect.objectContaining({
    method: "POST",
    body: JSON.stringify({ type: "CODE_CHANGE", title: "Architecture review", goal: "Review module boundaries.", context: null, project_id: null }),
  }));
});

it("edits and cancels only through revision-checked mission patches", async () => {
  let patchCount = 0;
  const fetchMock = vi.fn((url: string, options?: RequestInit) => {
    if (!options?.method) return Promise.resolve(reply(url.endsWith(mission.id) ? mission : [mission]));
    patchCount += 1;
    return Promise.resolve(reply(patchCount === 1
      ? { ...mission, title: "Reviewed JARVIS", revision: 2 }
      : { ...mission, title: "Reviewed JARVIS", status: "CANCELLED", revision: 3 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<MissionPanel projects={projects} />);

  await screen.findByText("Review JARVIS");
  fireEvent.click(screen.getByRole("button", { name: "View mission Review JARVIS" }));
  await screen.findByLabelText("Mission details");
  fireEvent.click(screen.getByRole("button", { name: "EDIT" }));
  fireEvent.change(screen.getByLabelText("Mission title"), { target: { value: "Reviewed JARVIS" } });
  fireEvent.click(screen.getByRole("button", { name: "SAVE CHANGES" }));
  await waitFor(() => expect(screen.getByLabelText("Mission details")).toHaveTextContent("Reviewed JARVIS"));
  fireEvent.click(screen.getByRole("button", { name: "CANCEL MISSION" }));

  await waitFor(() => expect(screen.getByLabelText("Mission details")).toHaveTextContent("CANCELLED"));
  const patchCalls = fetchMock.mock.calls.filter(([, options]) => options?.method === "PATCH");
  expect(patchCalls).toHaveLength(2);
  expect(patchCalls[0][1]).toEqual(expect.objectContaining({ body: expect.stringContaining('"expected_revision":1') }));
  expect(patchCalls[1][1]).toEqual(expect.objectContaining({ body: JSON.stringify({ expected_revision: 2, status: "CANCELLED" }) }));
});
