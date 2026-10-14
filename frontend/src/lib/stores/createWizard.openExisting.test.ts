import { beforeEach, describe, expect, it, vi } from "vitest";

// A fake filesystem: path -> { parent, isProject }.
type Node = { parent: string | null; isProject: boolean };
let fs: Record<string, Node> = {};

vi.mock("@/lib/api", () => ({
  api: {
    listDirectories: vi.fn(async (path: string) => {
      const node = fs[path];
      if (!node) throw new Error(`no such folder: ${path}`);
      return {
        path,
        parent_path: node.parent,
        directories: [],
        is_project: node.isProject,
        within_root: false,
      };
    }),
  },
}));

import { api } from "@/lib/api";
import { createWizard } from "@/lib/stores/createWizard.svelte";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

async function pick(path: string) {
  createWizard.chooseOpen();
  createWizard.onPickFolder(path);
  await settle();
}

beforeEach(() => {
  createWizard.close();
  createWizard.defaultProjectsFolder = "";
  createWizard.onError = () => {};
  createWizard.onSaveRootFolder = async (folder) => {
    createWizard.defaultProjectsFolder = folder;
  };
  createWizard.onOpenProject = async () => true;
  createWizard.onSaveAppPolicy = async () => {};
  fs = {
    "D:\\Books": { parent: "D:\\", isProject: false },
    "D:\\Books\\World": { parent: "D:\\Books", isProject: true },
    "D:\\Books\\World\\Series": { parent: "D:\\Books\\World", isProject: true },
    "D:\\Books\\World\\Series\\Book": { parent: "D:\\Books\\World\\Series", isProject: true },
    "D:\\Books\\Solo": { parent: "D:\\Books", isProject: true },
    "D:\\Books\\Plain": { parent: "D:\\Books", isProject: false },
    "D:\\": { parent: null, isProject: true },
  };
  createWizard.start();
});

describe("createWizard Welcome step (#2467)", () => {
  it("is the first step on a first run, and absent on a returning run", () => {
    expect(createWizard.currentStep.id).toBe("start");
    expect(createWizard.canAdvance).toBe(false);
    createWizard.close();
    createWizard.defaultProjectsFolder = "C:/projects";
    createWizard.start();
    expect(createWizard.steps.map((s) => s.id)).not.toContain("start");
    expect(createWizard.currentStep.id).toBe("location");
  });

  it("Create advances to the root step", () => {
    createWizard.chooseCreate();
    expect(createWizard.currentStep.id).toBe("root");
  });

  it("saving the root after Create still lands on location", async () => {
    createWizard.chooseCreate();
    createWizard.rootFolderDraft = "C:/projects";
    await createWizard.next();
    expect(createWizard.currentStep.id).toBe("location");
  });
});

describe("createWizard Open path (#2467)", () => {
  it("a non-project folder shows an error and stays on start", async () => {
    await pick("D:\\Books\\Plain");
    expect(createWizard.currentStep.id).toBe("start");
    expect(createWizard.openError).toContain("isn't a project");
  });

  it("cancelling the picker leaves the wizard on start", () => {
    createWizard.chooseOpen();
    expect(createWizard.pickerOpen).toBe(true);
    createWizard.closePicker();
    expect(createWizard.currentStep.id).toBe("start");
    expect(createWizard.open).toBe(true);
  });

  it("suggests the parent of the topmost ancestor project", async () => {
    await pick("D:\\Books\\World\\Series\\Book");
    expect(createWizard.currentStep.id).toBe("open_root");
    expect(createWizard.rootFolderDraft).toBe("D:\\Books");
    expect(createWizard.canAdvance).toBe(true);
  });

  it("suggests the parent of a standalone project", async () => {
    await pick("D:\\Books\\Solo");
    expect(createWizard.rootFolderDraft).toBe("D:\\Books");
  });

  it("requires the root to contain the project (separator-aware, case-insensitive)", async () => {
    await pick("D:\\Books\\Solo");
    createWizard.rootFolderDraft = "D:\\Books2";
    expect(createWizard.canAdvance).toBe(false);
    createWizard.rootFolderDraft = "d:\\BOOKS";
    expect(createWizard.canAdvance).toBe(true);
    createWizard.rootFolderDraft = "D:\\Books\\Solo";
    expect(createWizard.canAdvance).toBe(false);
  });

  it("Open saves the root, then opens the project, then closes", async () => {
    const calls: string[] = [];
    createWizard.onSaveRootFolder = async (folder) => {
      calls.push(`save:${folder}`);
      createWizard.defaultProjectsFolder = folder;
    };
    createWizard.onOpenProject = async (path) => {
      calls.push(`open:${path}`);
      return true;
    };
    await pick("D:\\Books\\Solo");
    await createWizard.confirmOpen();
    expect(calls).toEqual(["save:D:\\Books", "open:D:\\Books\\Solo"]);
    expect(createWizard.open).toBe(false);
  });

  it("a failed open keeps the wizard open on the open step", async () => {
    createWizard.onOpenProject = async () => false;
    await pick("D:\\Books\\Solo");
    await createWizard.confirmOpen();
    expect(createWizard.open).toBe(true);
    expect(createWizard.currentStep.id).toBe("open_root");
    expect(createWizard.openError).toBeTruthy();
  });

  it("a failed root save keeps the wizard open and never opens", async () => {
    const onOpenProject = vi.fn(async () => true);
    createWizard.onSaveRootFolder = async () => {};
    createWizard.onOpenProject = onOpenProject;
    await pick("D:\\Books\\Solo");
    await createWizard.confirmOpen();
    expect(onOpenProject).not.toHaveBeenCalled();
    expect(createWizard.open).toBe(true);
    expect(createWizard.openError).toBeTruthy();
  });

  it("Back from the open step returns to start", async () => {
    await pick("D:\\Books\\Solo");
    createWizard.back();
    expect(createWizard.currentStep.id).toBe("start");
    expect(createWizard.openProjectPath).toBe("");
  });
});

describe("createWizard Open path AI policy (#2467)", () => {
  it("persists the chosen policy app-wide: save root, then policy, then open", async () => {
    const calls: string[] = [];
    createWizard.onSaveRootFolder = async (folder) => {
      calls.push(`save:${folder}`);
      createWizard.defaultProjectsFolder = folder;
    };
    createWizard.onSaveAppPolicy = async (policy) => {
      calls.push(`policy:${policy}`);
    };
    createWizard.onOpenProject = async (path) => {
      calls.push(`open:${path}`);
      return true;
    };
    await pick("D:\\Books\\Solo");
    createWizard.setAiPolicy("cloud-allowed");
    await createWizard.confirmOpen();
    expect(calls).toEqual(["save:D:\\Books", "policy:cloud-allowed", "open:D:\\Books\\Solo"]);
    expect(createWizard.open).toBe(false);
  });

  it("writes nothing when the policy is left at its default", async () => {
    const onSaveAppPolicy = vi.fn(async () => {});
    createWizard.onSaveAppPolicy = onSaveAppPolicy;
    await pick("D:\\Books\\Solo");
    await createWizard.confirmOpen();
    expect(onSaveAppPolicy).not.toHaveBeenCalled();
    expect(createWizard.open).toBe(false);
  });

  it("a failed policy write keeps the wizard open and never opens", async () => {
    const onOpenProject = vi.fn(async () => true);
    createWizard.onSaveAppPolicy = async () => false;
    createWizard.onOpenProject = onOpenProject;
    await pick("D:\\Books\\Solo");
    createWizard.setAiPolicy("local-only");
    await createWizard.confirmOpen();
    expect(onOpenProject).not.toHaveBeenCalled();
    expect(createWizard.open).toBe(true);
    expect(createWizard.currentStep.id).toBe("open_root");
    expect(createWizard.openError).toBeTruthy();
  });

  it("a thrown policy write is surfaced the same way", async () => {
    createWizard.onSaveAppPolicy = async () => {
      throw new Error("boom");
    };
    await pick("D:\\Books\\Solo");
    createWizard.setAiPolicy("local-only");
    await createWizard.confirmOpen();
    expect(createWizard.open).toBe(true);
    expect(createWizard.openError).toBeTruthy();
  });

  it("Back to Welcome forgets the policy picked on the open step", async () => {
    await pick("D:\\Books\\Solo");
    createWizard.setAiPolicy("cloud-allowed");
    createWizard.back();
    expect(createWizard.aiPolicy).toBe("inherit");
  });
});

describe("createWizard Open pick race (#2467)", () => {
  function deferListing() {
    let resolve!: () => void;
    const gate = new Promise<void>((r) => {
      resolve = r;
    });
    vi.mocked(api.listDirectories).mockImplementationOnce(async (path?: string) => {
      await gate;
      return {
        path: path ?? "",
        parent_path: "D:\\Books",
        directories: [],
        is_project: true,
        within_root: false,
      };
    });
    return resolve;
  }

  it("choosing Create while a pick is in flight keeps the wizard on root", async () => {
    const release = deferListing();
    createWizard.chooseOpen();
    createWizard.onPickFolder("D:\\Books\\Solo");
    createWizard.chooseCreate();
    release();
    await settle();
    expect(createWizard.currentStep.id).toBe("root");
    expect(createWizard.rootFolderDraft).toBe("");
    expect(createWizard.openProjectPath).toBe("");
  });

  it("closing while a pick is in flight leaves the wizard untouched", async () => {
    const release = deferListing();
    createWizard.chooseOpen();
    createWizard.onPickFolder("D:\\Books\\Solo");
    createWizard.close();
    release();
    await settle();
    expect(createWizard.open).toBe(false);
    expect(createWizard.rootFolderDraft).toBe("");
    expect(createWizard.openProjectPath).toBe("");
  });
});

describe("createWizard Back after a failed open (#2467)", () => {
  it("returns to a Welcome with both choices, and Create skips the saved root", async () => {
    createWizard.onOpenProject = async () => false;
    await pick("D:\\Books\\Solo");
    await createWizard.confirmOpen();
    expect(createWizard.defaultProjectsFolder).toBe("D:\\Books");
    createWizard.back();
    expect(createWizard.currentStep.id).toBe("start");
    expect(createWizard.steps.map((s) => s.id)).toContain("start");
    // Both choices work from here: Open again, and Create straight to location.
    createWizard.chooseOpen();
    expect(createWizard.pickerOpen).toBe(true);
    createWizard.closePicker();
    createWizard.chooseCreate();
    expect(createWizard.currentStep.id).toBe("location");
    expect(createWizard.pickedFolder).toBe("D:\\Books");
  });

  it("the normal first-run Create path is unchanged: Welcome drops out after the root save", async () => {
    createWizard.chooseCreate();
    expect(createWizard.currentStep.id).toBe("root");
    createWizard.rootFolderDraft = "C:/projects";
    await createWizard.next();
    expect(createWizard.currentStep.id).toBe("location");
    expect(createWizard.steps.map((s) => s.id)).toEqual(["location", "ai", "review", "describe"]);
  });
});

describe("createWizard Open at a drive root (#2467)", () => {
  it("explains that a project at the top of a drive can't be opened", async () => {
    await pick("D:\\");
    expect(createWizard.currentStep.id).toBe("start");
    expect(createWizard.openError).toContain("top of a drive");
    expect(createWizard.openProjectPath).toBe("");
  });
});
