// The composition root of the backend HTTP client. Network primitives
// (`request`, `streamNdjson`, the raw fetch/WebSocket) live in `./api/core`;
// each domain's methods live in their own `./api/<domain>` module. This file
// only imports and composes them into the single `api` object every caller
// uses — see `./api/core` for the http-client-guard rationale (ADR-0056, #977).
import { aiApi } from "./api/ai";
import { assistantsApi } from "./api/assistants";
import { chatsApi } from "./api/chats";
import { loreApi } from "./api/lore";
import { manuscriptApi } from "./api/manuscript";
import { mutationsApi } from "./api/mutations";
import { mutationSetsApi } from "./api/mutationSets";
import { plotApi } from "./api/plot";
import { projectApi } from "./api/project";
import { promptsApi } from "./api/prompts";
import { researchApi } from "./api/research";
import { schemaApi } from "./api/schema";
import { searchApi } from "./api/search";
import { todosApi } from "./api/todos";
import { viewsApi } from "./api/views";

export { HttpError, setKeepaliveSaves, openSessionPresenceSocket } from "./api/core";
export type { AIStreamEvent } from "./api/core";
export type { ClientErrorReport } from "./api/core";

export const api = {
  ...projectApi,
  ...aiApi,
  ...manuscriptApi,
  ...researchApi,
  ...schemaApi,
  ...loreApi,
  ...promptsApi,
  ...plotApi,
  ...mutationSetsApi,
  ...assistantsApi,
  ...viewsApi,
  ...chatsApi,
  ...todosApi,
  ...mutationsApi,
  ...searchApi,
};
