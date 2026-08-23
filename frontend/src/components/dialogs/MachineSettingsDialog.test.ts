// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { reactive } from "@/lib/test/reactive.svelte";

// The dialog fetches the running app version (ADR-0072 S2) on first open —
// stub it so the mount is hermetic (#973's network guard fails any test that
// lets a real fetch through).
vi.mock("@/lib/api", () => ({
  api: {
    getVersion: vi.fn(async () => ({ version: "9.9.9", build: null })),
    checkForUpdate: vi.fn(),
  },
}));

import type { Mock } from "vitest";
import type { MachineSettingsDraft, MachineSettingsView, UpdateCheck } from "@/lib/types";
import type { AIHealthResponse } from "@/lib/aiTypes";
import { api } from "@/lib/api";
import MachineSettingsDialog from "@/components/dialogs/MachineSettingsDialog.svelte";

// The app-wide AI policy (#746) is deliberately NOT part of the batched draft:
// widening AI permission must be its own explicit gesture, never a side effect
// of the dialog's Save (decisions_ai_permission_fails_closed). These tests pin
// that contract — the rest of the dialog (providers/palette/storage) has its own
// coverage.

const DISPLAY = { ui_scale: 1.0, paragraph_align: "left" as const, paragraph_indent: false };

function view(ai_policy: MachineSettingsView["ai_policy"]): MachineSettingsView {
  return {
    version: 1,
    providers: { anthropic_api_key: "", openai_api_key: "", openrouter_api_key: "", ollama_host: "" },
    default_provider: "ollama",
    default_models: {},
    default_projects_folder: "",
    recent_projects: [],
    palette: [],
    display: DISPLAY,
    ai_policy,
    update_channel: "stable",
    config_path: "C:/config.yaml",
  };
}

function draft(): MachineSettingsDraft {
  return {
    anthropic_api_key: "",
    openai_api_key: "",
    openrouter_api_key: "",
    ollama_host: "",
    default_provider: "ollama",
    default_models: {},
    default_projects_folder: "",
    palette: [],
    display: { ...DISPLAY },
    update_channel: "stable",
  };
}

const radio = (name: string) => screen.getByRole("radio", { name }) as HTMLInputElement;
const applyBtn = () => screen.getByRole("button", { name: "Apply" }) as HTMLButtonElement;

function mount(ai_policy: MachineSettingsView["ai_policy"], onApplyPolicy = vi.fn().mockResolvedValue(true), onSave = vi.fn()) {
  render(MachineSettingsDialog, {
    props: {
      open: true,
      settings: view(ai_policy),
      draft: reactive(draft()),
      onCancel: () => {},
      onSave,
      onApplyPolicy,
      health: null,
    },
  });
  return { onApplyPolicy, onSave };
}

beforeEach(() => vi.clearAllMocks());

describe("MachineSettingsDialog — app-wide AI policy (#746)", () => {
  it("seeds the control from the persisted policy", () => {
    mount("cloud-allowed");
    expect(radio("Cloud allowed").checked).toBe(true);
    expect(radio("Off").checked).toBe(false);
  });

  it("disables Apply until the draft differs, then enables it", async () => {
    mount("off");
    expect(applyBtn().disabled).toBe(true); // nothing changed yet
    await fireEvent.click(radio("Cloud allowed"));
    expect(applyBtn().disabled).toBe(false);
  });

  it("a radio click alone never persists — only Apply commits", async () => {
    const { onApplyPolicy } = mount("off");
    await fireEvent.click(radio("Cloud allowed"));
    expect(onApplyPolicy).not.toHaveBeenCalled(); // fails closed

    await fireEvent.click(applyBtn());
    expect(onApplyPolicy).toHaveBeenCalledTimes(1);
    expect(onApplyPolicy).toHaveBeenCalledWith("cloud-allowed");
  });

  it("the dialog's Save never carries the policy — it is decoupled", async () => {
    const { onApplyPolicy, onSave } = mount("off");
    await fireEvent.click(radio("Cloud allowed")); // widen the draft
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledTimes(1); // the batched save ran
    expect(onApplyPolicy).not.toHaveBeenCalled(); // but the permission did NOT ride along
  });

  it("warns once the choice differs that Save won't apply it (#1382)", async () => {
    mount("off");
    expect(screen.queryByRole("status")).toBeNull(); // nothing changed yet — no nag
    await fireEvent.click(radio("Cloud allowed"));
    expect(screen.getByRole("status").textContent).toContain("Not applied");
  });

  it("surfaces the unapplied reminder from other tabs too (#1382)", async () => {
    mount("off");
    await fireEvent.click(radio("Cloud allowed"));
    // The AI tab shows the inline hint by the Apply button...
    expect(screen.getByRole("status").textContent).toContain("Not applied");
    // ...and moving toward Save via another tab still carries the reminder.
    await fireEvent.click(screen.getByRole("tab", { name: "Storage" }));
    expect(screen.getByRole("status").textContent).toContain("AI access change not applied");
  });
});

describe("MachineSettingsDialog — health names the resolved assistant (#336)", () => {
  function mountHealth(result: AIHealthResponse) {
    render(MachineSettingsDialog, {
      props: {
        open: true,
        settings: view("cloud-allowed"),
        draft: reactive(draft()),
        onCancel: () => {},
        onSave: vi.fn(),
        onApplyPolicy: vi.fn().mockResolvedValue(true),
        health: { checking: false, disabledReason: null, onCheck: vi.fn(), result },
      },
    });
  }

  it("names the resolved assistant on a passing ping so the tick isn't ambiguous", () => {
    mountHealth({
      provider: "anthropic",
      model: "claude-haiku",
      ok: true,
      latency_ms: 5,
      policy: "cloud-allowed",
      assistant_id: "cheap",
      assistant_name: "Cheap",
    });
    const line = screen.getByText(/Cheap/);
    expect(line.textContent).toContain("✓");
    expect(line.textContent).toContain("Cheap");
    expect(line.textContent).toContain("anthropic");
  });

  it("names the assistant on a failing ping too, so a red ✗ says which one broke", () => {
    mountHealth({
      provider: "anthropic",
      model: "m",
      ok: false,
      latency_ms: 0,
      policy: "cloud-allowed",
      error: "Anthropic API key is not configured.",
      assistant_id: "creative",
      assistant_name: "Creative",
    });
    const line = screen.getByText(/Creative/);
    expect(line.textContent).toContain("✗");
    expect(line.textContent).toContain("Creative");
    expect(line.textContent).toContain("not configured");
  });
});

describe("MachineSettingsDialog — running app version (ADR-0072 S2)", () => {
  it("fetches and shows the running version once the dialog is open", async () => {
    mount("off");
    expect(await screen.findByText("Version 9.9.9")).toBeInTheDocument();
  });
});

describe("MachineSettingsDialog — updates tab (ADR-0072 S7)", () => {
  const UP_TO_DATE: UpdateCheck = {
    channel: "stable",
    current_version: "9.9.9",
    current_build: null,
    update_available: false,
    latest: "v9.9.9",
    latest_url: null,
    reachable: true,
    detail: null,
  };

  const openUpdatesTab = () => fireEvent.click(screen.getByRole("tab", { name: "Updates" }));
  const channelRadio = (name: RegExp) => screen.getByRole("radio", { name }) as HTMLInputElement;
  const checkBtn = () => screen.getByRole("button", { name: /Check for updates/ }) as HTMLButtonElement;

  it("seeds the channel radios from the draft", async () => {
    mount("off");
    await openUpdatesTab();
    expect(channelRadio(/Stable/).checked).toBe(true);
    expect(channelRadio(/Bleeding edge/).checked).toBe(false);
  });

  it("links to the release page when a newer version exists", async () => {
    (api.checkForUpdate as Mock).mockResolvedValue({
      ...UP_TO_DATE,
      update_available: true,
      latest: "v9.9.10",
      latest_url: "https://example.test/releases/v9.9.10",
    });
    mount("off");
    await openUpdatesTab();
    await fireEvent.click(checkBtn());
    const link = (await screen.findByRole("link", { name: /release page/ })) as HTMLAnchorElement;
    expect(link.href).toContain("v9.9.10");
  });

  it("reports 'on the latest' when nothing is newer", async () => {
    (api.checkForUpdate as Mock).mockResolvedValue(UP_TO_DATE);
    mount("off");
    await openUpdatesTab();
    await fireEvent.click(checkBtn());
    expect(await screen.findByText(/on the latest version/)).toBeInTheDocument();
  });

  it("reports an unreachable check calmly (offline), never as an error", async () => {
    (api.checkForUpdate as Mock).mockResolvedValue({
      ...UP_TO_DATE,
      reachable: false,
      latest: null,
      detail: "offline",
    });
    mount("off");
    await openUpdatesTab();
    await fireEvent.click(checkBtn());
    expect(await screen.findByText(/Couldn't reach GitHub/)).toBeInTheDocument();
  });

  it("blocks the check on an unsaved channel change and nudges a Save", async () => {
    mount("off"); // saved channel is stable
    await openUpdatesTab();
    await fireEvent.click(channelRadio(/Bleeding edge/)); // draft now diverges
    expect(checkBtn().disabled).toBe(true);
    expect(screen.getByText(/Save to check on the/)).toBeInTheDocument();
    expect(api.checkForUpdate).not.toHaveBeenCalled();
  });

  it("drops an in-flight result if the channel changed before it resolved", async () => {
    // A deferred check: switch channel mid-flight, then resolve — the stale
    // saved-channel verdict must not surface under the "Save to check" nudge.
    let resolveCheck!: (v: UpdateCheck) => void;
    (api.checkForUpdate as Mock).mockReturnValue(
      new Promise<UpdateCheck>((r) => (resolveCheck = r)),
    );
    mount("off");
    await openUpdatesTab();
    await fireEvent.click(checkBtn()); // in flight
    await fireEvent.click(channelRadio(/Bleeding edge/)); // switch mid-flight
    resolveCheck({
      ...UP_TO_DATE,
      update_available: true,
      latest: "v9.9.10",
      latest_url: "https://example.test/releases/v9.9.10",
    });
    await Promise.resolve(); // let the awaited assignment run
    expect(screen.queryByRole("link", { name: /release page/ })).toBeNull();
    expect(screen.getByText(/Save to check on the/)).toBeInTheDocument();
  });
});
