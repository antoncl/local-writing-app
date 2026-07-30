// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "@/lib/api";

const fetchMock = () => fetch as unknown as ReturnType<typeof vi.fn>;

describe("api.logClientError", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(undefined));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs the report as JSON to /api/log", async () => {
    await api.logClientError({ message: "kaboom", context: "run", detail: "stack" });
    expect(fetchMock()).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock().mock.calls[0];
    expect(String(url)).toMatch(/\/api\/log$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      message: "kaboom",
      context: "run",
      detail: "stack",
    });
  });

  it("swallows a failed transport and never rejects (#386)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await expect(api.logClientError({ message: "x" })).resolves.toBeUndefined();
  });
});
