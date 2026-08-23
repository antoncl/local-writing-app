"""Poll GitHub Releases for a newer build (ADR-0072 S6, #1362).

The "subscribe to updates / know when a new one is out" feature (#173 points
4–5). This is the **check** half — it reads the channel, asks GitHub what the
latest is, and reports whether it's newer. It never downloads or replaces
anything: option A is "notify + link to the release page", which is safe,
platform-independent, and fully testable with a mocked HTTP response.

Two channels, two comparisons:
  - **stable** compares the latest `v*` release tag to the running version.
  - **nightly** compares the `nightly` tag's commit to the build stamp this
    binary was frozen at (`build_info.build_stamp`) — because every nightly
    reports the same `0.9.x`, only the commit distinguishes them.

Everything degrades gracefully: offline, rate-limited, a malformed response, or
a release that doesn't exist yet all yield `reachable`/`detail` rather than an
exception, and `update_available` stays `False` unless a comparison is positive.
"""
from __future__ import annotations

import httpx

from app.models import UpdateChannel, UpdateCheck

# The public repo the releases live in (ADR-0072 §5). Unauthenticated GitHub API
# access is 60 requests/hour per IP — ample for a human-triggered check.
GITHUB_REPO = "antoncl/local-writing-app"
_API = f"https://api.github.com/repos/{GITHUB_REPO}"
# The rolling nightly's release page — a stable URL (the tag is force-moved, the
# page path is constant), so option A can link to it without a second request.
_NIGHTLY_PAGE = f"https://github.com/{GITHUB_REPO}/releases/tag/nightly"

# Short enough that an offline user isn't left waiting on a manual check.
_TIMEOUT_SECONDS = 6.0
_HEADERS = {
    # GitHub rejects API requests with no User-Agent.
    "User-Agent": "local-writing-app-updater",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def check_for_update(
    channel: UpdateChannel,
    current_version: str,
    current_build: str | None,
) -> UpdateCheck:
    """Ask GitHub whether `channel` has something newer than what's running."""
    result = UpdateCheck(
        channel=channel,
        current_version=current_version,
        current_build=current_build,
    )
    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS, headers=_HEADERS) as client:
            if channel == "stable":
                _check_stable(client, result)
            else:
                _check_nightly(client, result)
    except httpx.HTTPError as exc:
        # Offline, DNS failure, timeout, rate-limit-as-error — anything that kept
        # us from a verdict. Not alarming: "couldn't check", never "up to date".
        result.reachable = False
        result.detail = str(exc) or exc.__class__.__name__
    return result


def _check_stable(client: httpx.Client, result: UpdateCheck) -> None:
    # `releases/latest` excludes prereleases, so it never returns the nightly.
    response = client.get(f"{_API}/releases/latest")
    if response.status_code == 404:
        # No stable release cut yet — reachable, but nothing to compare against.
        result.detail = "no stable release yet"
        return
    response.raise_for_status()
    data = response.json()
    tag = data.get("tag_name") if isinstance(data, dict) else None
    result.latest = tag
    result.latest_url = data.get("html_url") if isinstance(data, dict) else None
    result.update_available = _version_gt(tag, result.current_version)


def _check_nightly(client: httpx.Client, result: UpdateCheck) -> None:
    # The git ref, not the release's `target_commitish`: a lightweight tag's ref
    # resolves straight to the commit SHA, whereas `target_commitish` can come
    # back as the branch name ("master") depending on how the release was cut.
    response = client.get(f"{_API}/git/refs/tags/nightly")
    if response.status_code == 404:
        result.detail = "no nightly build yet"
        return
    response.raise_for_status()
    data = response.json()
    obj = data.get("object") if isinstance(data, dict) else None
    sha = obj.get("sha") if isinstance(obj, dict) else None
    if not isinstance(sha, str) or not sha:
        result.detail = "nightly ref has no commit"
        return
    # Only now that the ref exists: point at the page, so a "no nightly yet"
    # result never carries a link to a release page that 404s (mirrors the
    # stable path, which sets latest_url only on the 200 response).
    result.latest_url = _NIGHTLY_PAGE
    result.latest = sha[:12]
    if not result.current_build:
        # A source run, or a frozen build with no stamp: we can see the nightly
        # but can't tell if this is it. Report the fact rather than guessing.
        result.detail = "no build stamp to compare"
        return
    result.update_available = sha != result.current_build


def _parse_version(raw: str | None) -> tuple[int, ...] | None:
    """A `v0.9.5` / `0.9.5` tag as a comparable tuple, or `None` if not numeric.

    Deliberately tiny — no dependency on `packaging` — because the tags this
    compares are the project's own plain `MAJOR.MINOR.PATCH`. Anything with a
    pre-release / build suffix (`-rc1`, `+meta`) is truncated to its release
    core; a non-numeric component yields `None`, which makes the comparison
    conservatively report "not newer" rather than crash.
    """
    if not raw:
        return None
    core = raw.strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    try:
        return tuple(int(part) for part in core.split("."))
    except ValueError:
        return None


def _version_gt(latest: str | None, current: str | None) -> bool:
    """Is `latest` a strictly newer version than `current`? False if either is
    unparseable — an unknown comparison must never claim an update exists."""
    latest_parsed = _parse_version(latest)
    current_parsed = _parse_version(current)
    if latest_parsed is None or current_parsed is None:
        return False
    return latest_parsed > current_parsed
