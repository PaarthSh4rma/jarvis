import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApprovalPanel } from "./approval-panel";

const approval = {
  id: "22222222-2222-4222-8222-222222222222",
  mission_id: "11111111-1111-4111-8111-111111111111",
  action_type: "WORKSPACE_EDIT",
  summary: "Allow bounded workspace edits",
  risk_context: "Changes remain inside the selected project.",
  status: "PENDING",
  created_at: "2026-10-07T00:00:00Z",
  resolved_at: null,
  resolution_note: null,
};
const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("renders approval mission association, summary, risk, and status", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([approval])));
  render(<ApprovalPanel />);

  expect(await screen.findByText("Allow bounded workspace edits")).toBeInTheDocument();
  expect(screen.getByText(approval.mission_id)).toBeInTheDocument();
  expect(screen.getByText("Changes remain inside the selected project.")).toBeInTheDocument();
  expect(screen.getAllByText("PENDING").length).toBeGreaterThan(0);
});

it("records an approval decision without dispatching execution", async () => {
  const resolved = { ...approval, status: "APPROVED", resolved_at: "2026-10-07T00:01:00Z", resolution_note: "Reviewed locally." };
  const fetchMock = vi.fn((url: string, options?: RequestInit) => Promise.resolve(
    options?.method === "POST" ? reply(resolved) : reply([approval]),
  ));
  vi.stubGlobal("fetch", fetchMock);
  render(<ApprovalPanel />);

  await screen.findByText("Allow bounded workspace edits");
  fireEvent.change(screen.getByLabelText("Decision note for Allow bounded workspace edits"), { target: { value: "Reviewed locally." } });
  fireEvent.click(screen.getByRole("button", { name: "RECORD APPROVAL" }));

  expect(await screen.findByText("Decision recorded. No action executed.")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("APPROVED")).toBeInTheDocument());
  expect(fetchMock).toHaveBeenCalledWith(
    `http://localhost:8000/approvals/${approval.id}/resolve`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ status: "APPROVED", resolution_note: "Reviewed locally." }),
    }),
  );
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/runs") || String(url).includes("/execute"))).toBe(false);
  expect(screen.queryByRole("button", { name: /run|execute/i })).not.toBeInTheDocument();
});
