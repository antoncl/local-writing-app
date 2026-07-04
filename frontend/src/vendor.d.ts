/// <reference types="vite/client" />

declare module "turndown" {
  type TurndownRule = {
    filter: string | string[] | ((node: Node) => boolean);
    replacement: (content: string, node: Node) => string;
  };

  export default class TurndownService {
    constructor(options?: Record<string, unknown>);
    addRule(key: string, rule: TurndownRule): this;
    turndown(html: string): string;
    use(plugin: (service: TurndownService) => void | Array<(service: TurndownService) => void>): this;
  }
}

declare module "turndown-plugin-gfm" {
  import type TurndownService from "turndown";

  export function gfm(service: TurndownService): void;
}

declare module "katex" {
  interface KatexOptions {
    displayMode?: boolean;
    throwOnError?: boolean;
    output?: "html" | "mathml" | "htmlAndMathml";
    strict?: boolean | string | ((errorCode: string, errorMsg: string) => string);
    trust?: boolean;
    macros?: Record<string, string>;
  }
  export function renderToString(tex: string, options?: KatexOptions): string;
  const katex: { renderToString: typeof renderToString };
  export default katex;
}

declare module "katex/dist/katex.min.css";

declare module "dompurify" {
  interface DOMPurifyConfig {
    ALLOWED_TAGS?: string[];
    ALLOWED_ATTR?: string[];
    ADD_TAGS?: string[];
    ADD_ATTR?: string[];
    FORBID_TAGS?: string[];
    FORBID_ATTR?: string[];
    USE_PROFILES?: { html?: boolean; svg?: boolean; mathMl?: boolean };
    RETURN_TRUSTED_TYPE?: boolean;
  }
  interface DOMPurifyI {
    sanitize(dirty: string, config?: DOMPurifyConfig): string;
  }
  const DOMPurify: DOMPurifyI;
  export default DOMPurify;
}
