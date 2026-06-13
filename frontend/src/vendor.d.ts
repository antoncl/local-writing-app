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
