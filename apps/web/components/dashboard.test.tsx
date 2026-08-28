import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Dashboard } from "./dashboard";

describe("Dashboard", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the API-backed online state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok", service: "jarvis-api", version: "0.1.0" }) }));
    render(<Dashboard />);
    expect(screen.getByText("CONNECTING")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("ONLINE")).toBeInTheDocument());
    expect(screen.getByText("JARVIS-API")).toBeInTheDocument();
  });

  it("shows offline when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("unreachable")));
    render(<Dashboard />);
    await waitFor(() => expect(screen.getByText("OFFLINE")).toBeInTheDocument());
  });
});
