// A one-shot request to open the in-app guide viewer AT a specific guide, rather
// than the default landing guide (guides[0]). GuideView selects the default on
// mount; a caller that needs a particular guide — the prompt editor's "?" wants
// the Writing prompts guide, not whatever happens to be first — sets a request
// here just before revealing the pane, and GuideView consumes it. Partially
// implements #1295 (open at a specific guide); full deep-linking (URLs, arbitrary
// call sites) is still that issue.
//
// One-shot on purpose: after GuideView applies the request it clears it, so a
// later Help → Guides open (no request) keeps the viewer's own default/last
// selection, and a second "?" click re-fires cleanly (null → id is a real change,
// so GuideView's effect runs again).

let requestedId = $state<string | null>(null);

export const guideTarget = {
  get requestedId(): string | null {
    return requestedId;
  },
  /** Ask the viewer to open at this guide id the next time it reads the request. */
  request(id: string): void {
    requestedId = id;
  },
  /** Clear the pending request (called by GuideView once it has applied it). */
  consume(): void {
    requestedId = null;
  },
};
