#!/usr/bin/env bash
# Reset local-writing-app to a completely fresh install (Linux / Raspberry Pi):
# delete all machine-global state so first-run onboarding runs again.
#
# Removes the app config dir:
#   ${XDG_CONFIG_HOME:-$HOME/.config}/local-writing-app/
# which holds config.yaml (settings + provider API keys), assistants/,
# assistant-tags.yaml, and errors.log. That directory is the ONLY machine-global
# state on disk (no keyring, no update-staging, no hidden data dir).
#
# Your writing PROJECTS are NOT touched unless you pass --purge-projects.
#
# A shell script CANNOT clear the app's browser state: localStorage
# 'lastOpenedProjectPath' auto-reopens your last project and skips onboarding.
# Test in a fresh/incognito browser window, or clear the app's site data.
#
# Usage:
#   ./reset-fresh-install.sh                 # confirm, then delete config dir
#   ./reset-fresh-install.sh --force         # skip the confirmation
#   ./reset-fresh-install.sh --purge-projects  # also delete projects (asks DELETE)
set -euo pipefail

APP_NAME="local-writing-app"
FORCE=0
PURGE_PROJECTS=0
for arg in "$@"; do
    case "$arg" in
        -f|--force) FORCE=1 ;;
        --purge-projects) PURGE_PROJECTS=1 ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP_NAME"
CONFIG_FILE="$CONFIG_DIR/config.yaml"

echo "local-writing-app - reset to fresh install (Linux/RPi)"
echo "Config dir: $CONFIG_DIR"

if [ ! -d "$CONFIG_DIR" ]; then
    echo "Already clean - no config directory found. Nothing to do."
    exit 0
fi

# Surface the projects folder (kept unless --purge-projects). Line-scan only, so
# we never echo the API keys stored in the same file. Parse failure is harmless:
# --purge-projects still guards on the path existing AND a typed confirmation.
PROJECTS_ROOT=""
if [ -f "$CONFIG_FILE" ]; then
    PROJECTS_ROOT="$(grep -m1 -E '^[[:space:]]*default_projects_folder:' "$CONFIG_FILE" \
        | sed -E 's/^[[:space:]]*default_projects_folder:[[:space:]]*//; s/^["'"'"']//; s/["'"'"']$//' || true)"
fi
if [ -n "$PROJECTS_ROOT" ]; then
    echo "default_projects_folder (your projects live here): $PROJECTS_ROOT"
else
    echo "default_projects_folder: (unset)"
fi

# For a clean test, stop the app/service first. On Linux an open file can still be
# unlinked, so deletion succeeds while running, but the app may rewrite state.
if [ "$FORCE" -ne 1 ]; then
    read -r -p "Delete the config directory (settings + API keys + assistants)? [y/N] " ans
    case "$ans" in
        y|Y|yes|YES) ;;
        *) echo "Aborted. Nothing deleted."; exit 1 ;;
    esac
fi

rm -rf -- "$CONFIG_DIR"
echo "Removed $CONFIG_DIR"

# --- optional, irreversible: delete the actual writing projects ---
if [ "$PURGE_PROJECTS" -eq 1 ]; then
    if [ -z "$PROJECTS_ROOT" ]; then
        echo "--purge-projects: no default_projects_folder was set; nothing to purge."
    else
        case "$PROJECTS_ROOT" in "~"*) PROJECTS_ROOT="${PROJECTS_ROOT/#\~/$HOME}";; esac
        if [ ! -d "$PROJECTS_ROOT" ]; then
            echo "--purge-projects: '$PROJECTS_ROOT' does not exist; nothing to purge."
        else
            echo ""
            echo "IRREVERSIBLE: this deletes ALL projects under:"
            echo "  $PROJECTS_ROOT"
            read -r -p "Type DELETE to confirm: " typed
            if [ "$typed" = "DELETE" ]; then
                rm -rf -- "$PROJECTS_ROOT"
                echo "Removed $PROJECTS_ROOT"
            else
                echo "Project purge skipped (confirmation not matched)."
            fi
        fi
    fi
fi

echo ""
echo "Done. Machine state cleared."
echo "ALSO clear the browser state, or the app reopens your last project and skips onboarding:"
echo "  - Easiest: open the app in a fresh/incognito browser window, OR"
echo "  - Clear site data (localStorage 'lastOpenedProjectPath') for the app's http://127.0.0.1:<port> origin."
