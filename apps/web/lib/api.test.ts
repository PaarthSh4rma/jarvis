import { afterEach, describe, expect, it, vi } from "vitest";
import { cancelRun, resolveApiUrl, streamRun } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("resolveApiUrl", () => {
  it("uses one matching loopback hostname for browser API requests", () => {
    expect(resolveApiUrl(undefined, { protocol: "http:", hostname: "127.0.0.1" })).toBe(
      "http://127.0.0.1:8000",
    );
    expect(resolveApiUrl(undefined, { protocol: "http:", hostname: "localhost" })).toBe(
      "http://localhost:8000",
    );
  });

  it("honours an explicit frontend API URL", () => {
    expect(
      resolveApiUrl("http://localhost:9000/", {
        protocol: "http:",
        hostname: "127.0.0.1",
      }),
    ).toBe("http://localhost:9000");
  });
});

describe("execution API", () => {
  it("parses ordered SSE events without duplicating deltas", async () => {
    const payloads = [
      { sequence: 1, type: "assistant.delta", timestamp: "now", data: { content: "Good " } },
      { sequence: 2, type: "assistant.delta", timestamp: "now", data: { content: "evening." } },
      { sequence: 3, type: "run.completed", timestamp: "now", data: { state: "COMPLETED" } },
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      payloads.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""),
      { status: 200 },
    )));
    const received: typeof payloads = [];

    await streamRun("run-id", "conversation-id", (event) => received.push(event as typeof payloads[number]));

    expect(received).toEqual(payloads);
  });

  it("sends cancellation with conversation ownership context", async () => {
    const response = { run_id: "run-id", conversation_id: "conversation-id", state: "CANCELLING", created_at: "now", started_at: "now", completed_at: null };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await cancelRun("run-id", "conversation-id");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/runs/run-id/cancel",
      expect.objectContaining({ body: JSON.stringify({ conversation_id: "conversation-id" }) }),
    );
  });
});
