import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryPanel } from "./memory-panel";

const jsonResponse = (body: unknown, ok = true, status = 200) => ({
  ok,
  status,
  json: async () => body,
});

const limits = {
  max_user_entries: 50,
  max_project_entries: 25,
  max_characters: 500,
  max_injected_characters: 2000,
};
const entry = {
  id: "11111111-1111-4111-8111-111111111111",
  scope: "user",
  project_id: null,
  project_name: null,
  content: "I prefer pnpm",
  created_at: "2026-09-07T00:00:00Z",
  updated_at: "2026-09-07T00:00:00Z",
};
const projects = [
  {
    id: "aaaaaaaaaaaaaaaa",
    name: "alpha",
    is_git_repository: true,
    branch: "main",
    is_dirty: false,
    latest_commit_message: null,
    latest_commit_timestamp: null,
    technologies: ["Python"],
  },
];

describe("MemoryPanel", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders loaded user memories", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ memories: [entry], ...limits })));
    render(<MemoryPanel projects={projects} />);
    await waitFor(() => expect(screen.getByText("I prefer pnpm")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "USER MEMORY" })).toHaveClass("active");
  });

  it("shows its loading state", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<MemoryPanel projects={projects} />);
    expect(screen.getByText("LOADING MEMORY...")).toBeInTheDocument();
  });

  it("adds a user memory", async () => {
    const fetchMock = vi.fn((url: string, options?: RequestInit) =>
      options?.method === "POST"
        ? Promise.resolve(jsonResponse(entry, true, 201))
        : Promise.resolve(jsonResponse({ memories: [], ...limits })),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryPanel projects={projects} />);
    await waitFor(() => expect(screen.getByText("NO USER MEMORY")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Memory content"), {
      target: { value: "I prefer pnpm" },
    });
    fireEvent.click(screen.getByRole("button", { name: /SAVE/ }));
    await waitFor(() => expect(screen.getByText("I prefer pnpm")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/memory",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ scope: "user", content: "I prefer pnpm", project_id: null }),
      }),
    );
  });

  it("edits a memory", async () => {
    const updated = { ...entry, content: "I prefer yarn" };
    vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) =>
      options?.method === "PATCH"
        ? Promise.resolve(jsonResponse(updated))
        : Promise.resolve(jsonResponse({ memories: [entry], ...limits })),
    ));
    render(<MemoryPanel projects={projects} />);
    await waitFor(() => expect(screen.getByText(entry.content)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Edit memory" }));
    fireEvent.change(screen.getByLabelText("Edit memory"), {
      target: { value: updated.content },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save memory edit" }));
    await waitFor(() => expect(screen.getByText(updated.content)).toBeInTheDocument());
  });

  it("deletes a memory", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string, options?: RequestInit) =>
      options?.method === "DELETE"
        ? Promise.resolve(jsonResponse(null, true, 204))
        : Promise.resolve(jsonResponse({ memories: [entry], ...limits })),
    ));
    render(<MemoryPanel projects={projects} />);
    await waitFor(() => expect(screen.getByText(entry.content)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Delete memory" }));
    await waitFor(() => expect(screen.queryByText(entry.content)).not.toBeInTheDocument());
  });

  it("distinguishes project memory and sends the selected opaque project ID", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ memories: [], ...limits }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryPanel projects={projects} />);
    fireEvent.click(screen.getByRole("button", { name: "PROJECT MEMORY" }));
    await waitFor(() => expect(screen.getByLabelText("Memory project")).toHaveValue(projects[0].id));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `http://localhost:8000/memory?scope=project&project_id=${projects[0].id}`,
        expect.objectContaining({ cache: "no-store" }),
      ),
    );
    expect(screen.queryByText(projects[0].id)).not.toBeInTheDocument();
  });

  it("shows controlled API errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false, 500)));
    render(<MemoryPanel projects={projects} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Memory is unavailable."));
  });
});
