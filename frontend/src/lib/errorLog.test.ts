// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";

// The reporter's only dependency is the api transport; stub it so we observe the
// exact report it ships without touching the network.
vi.mock("@/lib/api", () => ({ api: { logClientError: vi.fn() } }));

import { api } from "@/lib/api";
import { reportClientError, installGlobalErrorLogging } from "@/lib/errorLog";

const logMock = api.logClientError as unknown as ReturnType<typeof vi.fn>;
const lastReport = () => logMock.mock.calls.at(-1)?.[0];

beforeEach(() => {
  logMock.mockReset();
  logMock.mockResolvedValue(undefined);
});

describe("reportClientError", () => {
  it("maps an Error to its message plus a stack detail", () => {
    reportClientError(new Error("save failed"), "save-scene");
    expect(logMock).toHaveBeenCalledTimes(1);
    const report = lastReport();
    expect(report.message).toBe("save failed");
    expect(report.context).toBe("save-scene");
    expect(report.detail).toContain("save failed"); // the stack carries the message
  });

  it("stringifies a non-Error and carries no detail or context", () => {
    reportClientError("boom string");
    const report = lastReport();
    expect(report.message).toBe("boom string");
    expect(report.detail).toBeUndefined();
    expect(report.context).toBeUndefined();
  });

  it("returns void without throwing", () => {
    expect(reportClientError(new Error("x"))).toBeUndefined();
  });
});

describe("installGlobalErrorLogging", () => {
  it("forwards an uncaught window error", () => {
    installGlobalErrorLogging();
    const event = new Event("error") as Event & { error?: unknown };
    event.error = new Error("render boom");
    window.dispatchEvent(event);
    expect(logMock).toHaveBeenCalledTimes(1);
    const report = lastReport();
    expect(report.message).toBe("render boom");
    expect(report.context).toBe("window.onerror");
  });

  it("forwards an unhandled promise rejection", () => {
    installGlobalErrorLogging(); // already installed — idempotent
    const event = new Event("unhandledrejection") as Event & { reason?: unknown };
    event.reason = new Error("dropped");
    window.dispatchEvent(event);
    expect(logMock).toHaveBeenCalledTimes(1);
    expect(lastReport().context).toBe("unhandledrejection");
  });

  it("installs its listeners only once", () => {
    const spy = vi.spyOn(window, "addEventListener");
    installGlobalErrorLogging(); // installed by the earlier tests already
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
