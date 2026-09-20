import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDebouncedCommit } from "./debouncedCommit";

describe("createDebouncedCommit", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("coalesces a burst of schedules into one run after the delay", () => {
    const run = vi.fn();
    const commit = createDebouncedCommit(run, 600);
    commit.schedule();
    vi.advanceTimersByTime(300);
    commit.schedule();
    vi.advanceTimersByTime(300);
    expect(run).not.toHaveBeenCalled();
    expect(commit.pending).toBe(true);
    vi.advanceTimersByTime(300);
    expect(run).toHaveBeenCalledTimes(1);
    expect(commit.pending).toBe(false);
  });

  it("flush runs a pending commit now and disarms the timer", () => {
    const run = vi.fn();
    const commit = createDebouncedCommit(run, 600);
    commit.schedule();
    commit.flush();
    expect(run).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1000);
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("flush with nothing pending is a no-op", () => {
    const run = vi.fn();
    createDebouncedCommit(run, 600).flush();
    expect(run).not.toHaveBeenCalled();
  });

  it("cancel drops a pending commit without running it", () => {
    const run = vi.fn();
    const commit = createDebouncedCommit(run, 600);
    commit.schedule();
    commit.cancel();
    vi.advanceTimersByTime(1000);
    expect(run).not.toHaveBeenCalled();
    expect(commit.pending).toBe(false);
  });
});
