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
  version: "0.4.0",
  ollama: "online",
  model: "test-model",
};

const emptyProjects = { projects: [], recent_projects: [], count: 0, dirty_count: 0 };
const SESSION_ID = "11111111-1111-4111-8111-111111111111";
const NEW_SESSION_ID = "22222222-2222-4222-8222-222222222222";
const conversationResponse = (conversationId = SESSION_ID) => ({
  conversation_id: conversationId,
  expires_in_seconds: 1800,
  max_turns: 12,
  max_characters: 12000,
});
const RUN_ID = "33333333-3333-4333-8333-333333333333";
const runResponse = () => ({ run_id: RUN_ID, conversation_id: SESSION_ID, state: "QUEUED", created_at: new Date().toISOString(), started_at: null, completed_at: null });
const eventResponse = (content: string) => new Response(
  `data: ${JSON.stringify({ sequence: 1, type: "assistant.delta", timestamp: new Date().toISOString(), data: { content } })}\n\ndata: ${JSON.stringify({ sequence: 2, type: "run.completed", timestamp: new Date().toISOString(), data: { state: "COMPLETED" } })}\n\n`,
  { status: 200, headers: { "Content-Type": "text/event-stream" } },
);

describe("Dashboard", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("sends a message and renders the local assistant response", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (url.endsWith("/conversations")) {
        return Promise.resolve(jsonResponse(conversationResponse(), true, 201));
      }
      if (url.endsWith("/runs")) return Promise.resolve(jsonResponse(runResponse(), true, 201));
      return Promise.resolve(eventResponse("Ready when you are."));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Hello Jarvis" } });
    fireEvent.click(screen.getByLabelText("Send message"));

    expect(screen.getByText("Hello Jarvis")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Ready when you are.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ message: "Hello Jarvis", conversation_id: SESSION_ID }),
      }),
    );
  });

  it("shows a graceful runtime error when Ollama becomes unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (url.endsWith("/conversations")) {
        return Promise.resolve(jsonResponse(conversationResponse(), true, 201));
      }
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

  it("reuses the locally retained session for subsequent chat", async () => {
    window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (url.endsWith("/runs")) return Promise.resolve(jsonResponse(runResponse(), true, 201));
      return Promise.resolve(eventResponse("Context retained."));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Follow up" } });
    fireEvent.click(screen.getByLabelText("Send message"));
    await waitFor(() => expect(screen.getByText("Context retained.")).toBeInTheDocument());

    expect(fetchMock).not.toHaveBeenCalledWith(
      "http://localhost:8000/conversations",
      expect.anything(),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/runs",
      expect.objectContaining({
        body: JSON.stringify({ message: "Follow up", conversation_id: SESSION_ID }),
      }),
    );
  });

  it("resets the active session and clears the transcript", async () => {
    window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
    window.sessionStorage.setItem("jarvis.completed-transcript.v1", JSON.stringify({
      conversationId: SESSION_ID,
      messages: [{ id: 1, role: "assistant", content: "Stored old context." }],
    }));
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (options?.method === "DELETE") return Promise.resolve(jsonResponse(null, true, 204));
      if (url.endsWith("/conversations")) {
        return Promise.resolve(jsonResponse(conversationResponse(NEW_SESSION_ID), true, 201));
      }
      if (url.endsWith("/runs")) return Promise.resolve(jsonResponse(runResponse(), true, 201));
      return Promise.resolve(eventResponse("Old context."));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByLabelText("Send message"));
    await waitFor(() => expect(screen.getByText("Old context.")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "NEW SESSION" }));

    await waitFor(() => expect(screen.queryByText("Old context.")).not.toBeInTheDocument());
    expect(window.localStorage.getItem("jarvis.conversation-id")).toBe(NEW_SESSION_ID);
    expect(window.sessionStorage.getItem("jarvis.completed-transcript.v1")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/conversations/${SESSION_ID}`,
      { method: "DELETE" },
    );
  });

  it("handles an expired session without crashing", async () => {
    window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      return Promise.resolve(jsonResponse({ detail: "expired" }, false, 410));
    }));
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Continue" } });
    fireEvent.click(screen.getByLabelText("Send message"));

    await waitFor(() => expect(screen.getByText("SESSION UNAVAILABLE — START A NEW SESSION")).toBeInTheDocument());
    expect(window.localStorage.getItem("jarvis.conversation-id")).toBeNull();
  });

  it("offers STOP and sends an ownership-scoped cancellation", async () => {
    window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
    let streamController!: ReadableStreamDefaultController<Uint8Array>;
    const encoder = new TextEncoder();
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (url.endsWith("/runs")) return Promise.resolve(jsonResponse(runResponse(), true, 201));
      if (url.includes("/events?")) return Promise.resolve(new Response(new ReadableStream({ start(controller) { streamController = controller; } })));
      if (url.endsWith("/cancel")) {
        streamController.enqueue(encoder.encode(`data: ${JSON.stringify({ sequence: 2, type: "run.cancelled", timestamp: "now", data: { state: "CANCELLED" } })}\n\n`));
        streamController.close();
        return Promise.resolve(jsonResponse({ ...runResponse(), state: "CANCELLING" }));
      }
      return Promise.reject(new Error("Unexpected request"));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Wait" } });
    fireEvent.click(screen.getByLabelText("Send message"));
    const stop = await screen.findByLabelText("Stop execution");
    await waitFor(() => expect(stop).not.toBeDisabled());
    fireEvent.click(stop);

    await waitFor(() => expect(screen.getByText("EXECUTION CANCELLED")).toBeInTheDocument());
    expect(screen.queryByLabelText("Stop execution")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Enter a command")).toBeEnabled();
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/runs/${RUN_ID}/cancel`,
      expect.objectContaining({ body: JSON.stringify({ conversation_id: SESSION_ID }) }),
    );
  });

  it.each([
    ["run.failed", "EXECUTION FAILED SAFELY"],
    ["run.timed_out", "EXECUTION TIMED OUT"],
  ])("cleans up controls after %s", async (terminalType, label) => {
    window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (url.endsWith("/runs")) return Promise.resolve(jsonResponse(runResponse(), true, 201));
      if (url.includes("/events?")) return Promise.resolve(new Response(
        `data: ${JSON.stringify({ sequence: 1, type: terminalType, timestamp: "now", data: {} })}\n\n`,
        { status: 200 },
      ));
      return Promise.resolve(jsonResponse({ memories: [], max_user_entries: 50, max_project_entries: 25, max_characters: 500, max_injected_characters: 2000 }));
    }));
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Run" } });
    fireEvent.click(screen.getByLabelText("Send message"));

    await waitFor(() => expect(screen.getByText(label)).toBeInTheDocument());
    expect(screen.queryByLabelText("Stop execution")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Enter a command")).toBeEnabled();
  });

  it("renders progressive chunks once and permits the next request after completion", async () => {
    window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
    let runNumber = 0;
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (url.endsWith("/runs")) {
        runNumber += 1;
        return Promise.resolve(jsonResponse({ ...runResponse(), run_id: `${RUN_ID}-${runNumber}` }, true, 201));
      }
      const frames = ["Hello", " there", ", sir."].map((content, index) =>
        `data: ${JSON.stringify({ sequence: index + 1, type: "assistant.delta", timestamp: "now", data: { content } })}\n\n`,
      ).join("") + `data: ${JSON.stringify({ sequence: 4, type: "run.completed", timestamp: "now", data: {} })}\n\n`;
      return Promise.resolve(new Response(frames));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "First" } });
    fireEvent.click(screen.getByLabelText("Send message"));
    await waitFor(() => expect(screen.getByText("Hello there, sir.")).toBeInTheDocument());
    expect(screen.getAllByText("Hello there, sir.")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Second" } });
    fireEvent.click(screen.getByLabelText("Send message"));
    await waitFor(() => expect(runNumber).toBe(2));
  });

  it("restores a completed conversation after refresh without creating or duplicating a run", async () => {
    window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (url.endsWith("/runs")) return Promise.resolve(jsonResponse(runResponse(), true, 201));
      if (url.includes("/events?")) return Promise.resolve(eventResponse("Persisted response."));
      return Promise.resolve(jsonResponse({ memories: [], max_user_entries: 50, max_project_entries: 25, max_characters: 500, max_injected_characters: 2000 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const first = render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Persist me" } });
    fireEvent.click(screen.getByLabelText("Send message"));
    await waitFor(() => expect(screen.getByText("Persisted response.")).toBeInTheDocument());
    first.unmount();
    render(<Dashboard />);

    await waitFor(() => expect(screen.getByText("Persist me")).toBeInTheDocument());
    expect(screen.getAllByText("Persisted response.")).toHaveLength(1);
    expect(window.localStorage.getItem("jarvis.conversation-id")).toBe(SESSION_ID);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/runs"))).toHaveLength(1);
  });

  it("detaches an active stream on refresh without creating another run", async () => {
    window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
    const fetchMock = vi.fn((url: string, options?: RequestInit) => {
      if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
      if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
      if (url.endsWith("/runs")) return Promise.resolve(jsonResponse(runResponse(), true, 201));
      if (url.includes("/events?")) return new Promise((_, reject) => {
        options?.signal?.addEventListener("abort", () => reject(new DOMException("Detached", "AbortError")));
      });
      return Promise.resolve(jsonResponse({ memories: [], max_user_entries: 50, max_project_entries: 25, max_characters: 500, max_injected_characters: 2000 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const first = render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Still running" } });
    fireEvent.click(screen.getByLabelText("Send message"));
    await screen.findByLabelText("Stop execution");
    first.unmount();
    render(<Dashboard />);

    await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
    expect(window.localStorage.getItem("jarvis.conversation-id")).toBe(SESSION_ID);
    expect(screen.queryByText("Still running")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Stop execution")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/runs"))).toHaveLength(1);
  });

  it.each(["run.failed", "run.cancelled", "run.timed_out"])(
    "does not restore incomplete %s output after refresh",
    async (terminalType) => {
      window.localStorage.setItem("jarvis.conversation-id", SESSION_ID);
      const fetchMock = vi.fn((url: string) => {
        if (url.endsWith("/health")) return Promise.resolve(jsonResponse(onlineHealth));
        if (url.endsWith("/projects")) return Promise.resolve(jsonResponse(emptyProjects));
        if (url.endsWith("/runs")) return Promise.resolve(jsonResponse(runResponse(), true, 201));
        if (url.includes("/events?")) return Promise.resolve(new Response(
          `data: ${JSON.stringify({ sequence: 1, type: "assistant.delta", timestamp: "now", data: { content: "Partial" } })}\n\ndata: ${JSON.stringify({ sequence: 2, type: terminalType, timestamp: "now", data: {} })}\n\n`,
        ));
        return Promise.resolve(jsonResponse({ memories: [], max_user_entries: 50, max_project_entries: 25, max_characters: 500, max_injected_characters: 2000 }));
      });
      vi.stubGlobal("fetch", fetchMock);
      const first = render(<Dashboard />);
      await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
      fireEvent.change(screen.getByLabelText("Enter a command"), { target: { value: "Incomplete" } });
      fireEvent.click(screen.getByLabelText("Send message"));
      await waitFor(() => expect(screen.getByText("Partial")).toBeInTheDocument());
      first.unmount();
      render(<Dashboard />);

      await waitFor(() => expect(screen.getAllByText("ONLINE").length).toBeGreaterThan(0));
      expect(screen.queryByText("Partial")).not.toBeInTheDocument();
      expect(screen.queryByText("Incomplete")).not.toBeInTheDocument();
      expect(window.localStorage.getItem("jarvis.conversation-id")).toBe(SESSION_ID);
    },
  );
});
