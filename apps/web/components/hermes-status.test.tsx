import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { HermesStatus } from "./hermes-status";
import { Dashboard } from "./dashboard";

const online = {
  state: "ONLINE", version: "0.9.0", capabilities: [], reason: "verified",
  checked_at: "2026-10-04T00:00:00Z", last_successful_check: "2026-10-04T00:00:00Z",
};
const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.localStorage.clear(); });

it("shows verified online health and bounded capabilities", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(reply(
    url.endsWith("/capabilities") ? { ...online, version: null, capabilities: ["run_status"] } : online,
  ))));
  render(<HermesStatus />);
  expect(await screen.findByText("HERMES ONLINE / 0.9.0")).toBeInTheDocument();
  expect(screen.getByText("Advertised: run_status")).toBeInTheDocument();
  expect(screen.getByText(/Last successful health check/)).toBeInTheDocument();
});

it("shows offline without claiming worker readiness and allows retry", async () => {
  const fetchMock = vi.fn().mockResolvedValue(reply({
    ...online, state: "OFFLINE", version: null, reason: "unavailable", last_successful_check: null,
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<HermesStatus />);
  expect(await screen.findByText("HERMES OFFLINE")).toBeInTheDocument();
  fetchMock.mockImplementation(() => Promise.resolve(reply(online)));
  fireEvent.click(screen.getByRole("button", { name: "CHECK HERMES" }));
  expect(await screen.findByText("HERMES ONLINE / 0.9.0")).toBeInTheDocument();
});

it("distinguishes public health from authenticated capability access", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(reply(
    url.endsWith("/health") ? online : { ...online, state: "UNKNOWN", reason: "authentication_required" },
  ))));
  render(<HermesStatus />);
  expect(await screen.findByText("Capabilities require authentication")).toBeInTheDocument();
  expect(screen.getByText("HERMES ONLINE / 0.9.0")).toBeInTheDocument();
});

it("treats malformed responses as unknown", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(reply({ state: "ONLINE" }))));
  render(<HermesStatus />);
  expect(await screen.findByText("HERMES UNKNOWN")).toBeInTheDocument();
});

it.each([true, false])("keeps Hermes controls visible with Ollama offline (Hermes available: %s)", async (hermesAvailable) => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url.includes("/integrations/hermes/")) return hermesAvailable
      ? Promise.resolve(reply(online)) : Promise.reject(new Error("offline"));
    if (url.endsWith("/health")) return Promise.resolve(reply({
      status: "ok", service: "jarvis-api", version: "0.8.0", ollama: "offline", model: "local",
    }));
    if (url.endsWith("/projects")) return Promise.resolve(reply({ projects: [], recent_projects: [], count: 0, dirty_count: 0 }));
    if (url.endsWith("/skills")) return Promise.resolve(reply({ skills: [], count: 0 }));
    return Promise.resolve(reply({ memories: [], max_characters: 500 }));
  }));
  render(<Dashboard />);
  await waitFor(() => expect(screen.getByRole("button", { name: "CHECK HERMES" })).toBeEnabled());
  const panel = screen.getByRole("article", { name: "Hermes system status" });
  expect(within(panel).getByText(hermesAvailable ? "HERMES ONLINE / 0.9.0" : "HERMES UNAVAILABLE")).toBeInTheDocument();
  expect(screen.getByText("JARVIS")).toBeInTheDocument();
  expect(screen.getByLabelText("Send message")).toBeDisabled();
  expect(screen.getByRole("button", { name: "CREATE MISSION" })).toBeEnabled();
});
