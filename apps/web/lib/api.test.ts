import { describe, expect, it } from "vitest";
import { resolveApiUrl } from "./api";

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
