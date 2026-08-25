// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import type { ComponentProps } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { ProviderCredentialsView } from "@/lib/types";
import ProviderSubscriptions from "@/components/widgets/ProviderSubscriptions.svelte";

// The unified provider chooser (#1417): every provider is a chip, Ollama included
// (a url credential with a reachability test). The policy slider only widens the
// `allowed` scope — Local shows Ollama alone; Cloud adds the cloud subscriptions
// beside it. These tests lock that scope-and-kind behavior at the component level,
// which the Settings-dialog tests (always cloud-allowed) don't exercise.

type Props = ComponentProps<typeof ProviderSubscriptions>;

const EMPTY: ProviderCredentialsView = {
  anthropic_api_key: "",
  openai_api_key: "",
  openrouter_api_key: "",
  ollama_host: "http://127.0.0.1:11434",
};

const CLOUD_ALL = ["anthropic", "openai", "openrouter", "ollama"];

function mount(overrides: Partial<Props> = {}) {
  const onSaveKey = vi.fn();
  const onClearKey = vi.fn();
  const props = { providers: EMPTY, onSaveKey, onClearKey, ...overrides } as Props;
  render(ProviderSubscriptions, { props });
  return { onSaveKey, onClearKey };
}

const btn = (name: string | RegExp) => screen.queryByRole("button", { name });

describe("ProviderSubscriptions — the Local stop (allowed = ollama only)", () => {
  it("shows Ollama alone, editable, with nothing to add and no cloud chips", () => {
    // `editable` false = the wizard's add-only mode; a url provider is editable
    // regardless (you must be able to change its host).
    mount({ allowed: ["ollama"], editable: false });
    expect(screen.getByText("Ollama")).toBeTruthy();
    expect(screen.queryByText("Anthropic")).toBeNull();
    expect(btn("Edit Ollama")).toBeTruthy();
    expect(btn("+ Add provider")).toBeNull();
  });
});

describe("ProviderSubscriptions — the Cloud stop (allowed = every provider)", () => {
  it("shows a configured cloud provider beside Ollama, with the rest addable", () => {
    mount({
      providers: { ...EMPTY, anthropic_api_key: "sk-ant-real" },
      allowed: CLOUD_ALL,
      editable: false,
    });
    expect(screen.getByText("Anthropic")).toBeTruthy();
    expect(screen.getByText("Ollama")).toBeTruthy();
    expect(btn("+ Add provider")).toBeTruthy();
  });

  it("keeps cloud keys add-only in wizard mode — no edit/remove on a secret chip", () => {
    mount({
      providers: { ...EMPTY, anthropic_api_key: "sk-ant-real" },
      allowed: CLOUD_ALL,
      editable: false,
    });
    // The secret chip is not editable/removable here...
    expect(btn("Edit Anthropic")).toBeNull();
    expect(btn("Remove Anthropic")).toBeNull();
    // ...but the url chip always is.
    expect(btn("Edit Ollama")).toBeTruthy();
  });

  it("gives secrets rotate + remove in editable (Settings) mode", async () => {
    const { onClearKey } = mount({
      providers: { ...EMPTY, anthropic_api_key: "sk-ant-real" },
      allowed: CLOUD_ALL,
      editable: true,
    });
    expect(btn("Edit Anthropic")).toBeTruthy();
    await fireEvent.click(btn("Remove Anthropic")!);
    expect(onClearKey).toHaveBeenCalledWith("anthropic_api_key");
  });
});

describe("ProviderSubscriptions — editing the Ollama host", () => {
  it("reveals a text host field + Test, and saves the typed host", async () => {
    const { onSaveKey } = mount({
      allowed: ["ollama"],
      editable: false,
      onTestReachability: vi.fn(),
    });
    await fireEvent.click(btn("Edit Ollama")!);
    const host = screen.getByRole("textbox", { name: "Host URL" }) as HTMLInputElement;
    expect(host.type).toBe("text"); // a url credential, not a masked secret
    expect(btn("Test host")).toBeTruthy();
    await fireEvent.input(host, { target: { value: "http://raspberrypi.local:11434" } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSaveKey).toHaveBeenCalledWith("ollama_host", "http://raspberrypi.local:11434");
  });

  it("offers a masked key with no reachability test when adding a cloud provider", async () => {
    // A reachability probe is wired, yet a cloud secret still shows no Test — the
    // Test is gated on the descriptor's `hasReachabilityTest`, not on the callback.
    mount({ allowed: ["anthropic", "ollama"], editable: false, onTestReachability: vi.fn() });
    await fireEvent.click(btn("+ Add provider")!);
    const key = screen.getByLabelText("API key") as HTMLInputElement;
    expect(key.type).toBe("password");
    expect(btn("Test host")).toBeNull();
  });
});
