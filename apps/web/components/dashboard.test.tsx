import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Dashboard } from "./dashboard";

const jsonResponse = (body: unknown, ok = true, status = 200) => ({
  ok,
  status,
  json: async () => body,
});

const onlineHealth = {
  status: "ok",
  service: "jarvis-api",
  version: "0.2.0",
  ollama: "online",
  model: "test-model",
};

const emptyProjects = { projects: [], recent_projects: [], count: 0, dirty_count: 0 };

describe("Dashboard", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("sends a message and renders the local assistant response", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      return Promise.resolve(jsonResponse({ response: "Ready when you are.", model: "test-model", assistant: "jarvis" }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Hello Jarvis" } });
    fireEvent.click(screen.getByLabelText("Send message"));

    expect(screen.getByText("Hello Jarvis")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Ready when you are.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://localhost:8000/chat",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ message: "Hello Jarvis" }) }),
    );
  });

  it("shows a graceful runtime error when Ollama becomes unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      return Promise.resolve(jsonResponse({ detail: "Ollama is unavailable." }, false, 503));
    }));
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Status" } });
    fireEvent.click(screen.getByLabelText("Send message"));

    await waitFor(() => expect(screen.getByText("OLLAMA RUNTIME UNAVAILABLE — CHECK LOCAL SERVICE")).toBeInTheDocument());
    expect(screen.getByLabelText("Enter a command")).toBeDisabled();
  });

  it("keeps the API visible while reporting Ollama offline", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(
      url.endsWith("/health")
        ? jsonResponse({ ...onlineHealth, ollama: "offline" })
        : jsonResponse(emptyProjects),
    )));
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("OFFLINE").length).toBeGreaterThan(0));
    expect(screen.getByText("TEST-MODEL")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ollama runtime unavailable")).toBeDisabled();
  });

  it("does not crash when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("unreachable")));
    render(<Dashboard />);
    await waitFor(() => expect(screen.getAllByText("OFFLINE").length).toBeGreaterThan(0));
  });

  it("shows the compact project summary", async () => {
    const projects = {
      projects: [],
      recent_projects: [
        { id: "a", name: "jarvis", branch: "main", is_git_repository: true, is_dirty: true, latest_commit_message: "V0.3", latest_commit_timestamp: "2026-08-28T01:00:00Z", technologies: ["Python"] },
        { id: "b", name: "exohunter", branch: "develop", is_git_repository: true, is_dirty: false, latest_commit_message: "Fix", latest_commit_timestamp: "2026-08-27T01:00:00Z", technologies: ["Node.js"] },
      ],
      count: 7,
      dirty_count: 2,
    };
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(
      url.endsWith("/health") ? jsonResponse(onlineHealth) : jsonResponse(projects),
    )));
    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText("jarvis")).toBeInTheDocument());
    expect(screen.getByText("exohunter")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("reports project API failure without affecting chat health", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("/health")
      ? Promise.resolve(jsonResponse(onlineHealth))
      : Promise.resolve(jsonResponse({ detail: "failure" }, false, 500))));
    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText("PROJECT INDEX UNAVAILABLE")).toBeInTheDocument());
    expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0);
  });
});
