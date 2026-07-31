// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

import type { MachineSettingsDraft, MachineSettingsView } from "@/lib/types";
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
  };
}

const radio = (name: string) => screen.getByRole("radio", { name }) as HTMLInputElement;
const applyBtn = () => screen.getByRole("button", { name: "Apply" }) as HTMLButtonElement;

function mount(ai_policy: MachineSettingsView["ai_policy"], onApplyPolicy = vi.fn().mockResolvedValue(true), onSave = vi.fn()) {
  render(MachineSettingsDialog, {
    props: {
      open: true,
      settings: view(ai_policy),
      draft: draft(),
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
});
