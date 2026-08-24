<#
.SYNOPSIS
  Reset local-writing-app to a completely fresh install (Windows): delete all
  machine-global state so the first-run onboarding wizard runs again.

.DESCRIPTION
  Removes the app's config directory
      %APPDATA%\local-writing-app\
  which holds config.yaml (machine settings + provider API keys), assistants\,
  assistant-tags.yaml, and errors.log. That directory is the ONLY machine-global
  state on disk - there is no keyring, update-staging dir, or hidden data dir.

  Your writing PROJECTS are NOT touched unless you pass -PurgeProjects.

  A shell script CANNOT clear the app's browser state. The browser auto-reopens
  your last project via localStorage ('lastOpenedProjectPath'), which skips
  onboarding. Test in a fresh/InPrivate browser window, or clear site data for
  the app's http://127.0.0.1:<port> origin.

.PARAMETER Force
  Skip the confirmation prompt for deleting the config directory.

.PARAMETER PurgeProjects
  ALSO delete the writing projects under default_projects_folder. Irreversible;
  always requires typing DELETE, even with -Force.

.EXAMPLE
  .\reset-fresh-install.ps1
  .\reset-fresh-install.ps1 -Force
  .\reset-fresh-install.ps1 -PurgeProjects
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$PurgeProjects
)

$ErrorActionPreference = "Stop"
$AppName = "local-writing-app"

# Resolve the config dir exactly as the app does (machine_settings.config_dir):
# %APPDATA%\local-writing-app, with the Roaming default as fallback.
$base = $env:APPDATA
if (-not $base) { $base = Join-Path $HOME "AppData\Roaming" }
$configDir  = Join-Path $base $AppName
$configFile = Join-Path $configDir "config.yaml"

Write-Host "local-writing-app - reset to fresh install (Windows)" -ForegroundColor Cyan
Write-Host "Config dir: $configDir"

if (-not (Test-Path -LiteralPath $configDir)) {
    Write-Host "Already clean - no config directory found. Nothing to do." -ForegroundColor Green
    exit 0
}

# Surface the projects folder (kept unless -PurgeProjects). Line-scan only, so we
# never echo the API keys stored in the same file.
$projectsRoot = $null
if (Test-Path -LiteralPath $configFile) {
    $m = Select-String -LiteralPath $configFile -Pattern '^\s*default_projects_folder:\s*(.*)$' | Select-Object -First 1
    if ($m) { $projectsRoot = $m.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'") }
}
if ($projectsRoot) {
    Write-Host "default_projects_folder (your projects live here): $projectsRoot" -ForegroundColor Yellow
} else {
    Write-Host "default_projects_folder: (unset)"
}

# A running install can hold errors.log / config.yaml open and block deletion.
$proc = Get-Process -Name "LocalWritingApp" -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "WARNING: LocalWritingApp is running (PID $($proc.Id)). Close it first, or deletion may fail on locked files." -ForegroundColor Yellow
}

if (-not $Force) {
    $ans = Read-Host "Delete the config directory (settings + API keys + assistants)? [y/N]"
    if ($ans -notmatch '^(y|yes)$') {
        Write-Host "Aborted. Nothing deleted." -ForegroundColor Yellow
        exit 1
    }
}

try {
    Remove-Item -LiteralPath $configDir -Recurse -Force
    Write-Host "Removed $configDir" -ForegroundColor Green
} catch {
    Write-Host "FAILED to remove config dir: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Is the app still running? Close LocalWritingApp and retry." -ForegroundColor Red
    exit 1
}

# --- optional, irreversible: delete the actual writing projects ---
if ($PurgeProjects) {
    if (-not $projectsRoot) {
        Write-Host "-PurgeProjects: no default_projects_folder was set; nothing to purge." -ForegroundColor Yellow
    } elseif (-not (Test-Path -LiteralPath $projectsRoot)) {
        Write-Host "-PurgeProjects: '$projectsRoot' does not exist; nothing to purge." -ForegroundColor Yellow
    } else {
        Write-Host ""
        Write-Host "IRREVERSIBLE: this deletes ALL projects under:" -ForegroundColor Red
        Write-Host "  $projectsRoot" -ForegroundColor Red
        $typed = Read-Host "Type DELETE to confirm"
        if ($typed -ceq "DELETE") {
            Remove-Item -LiteralPath $projectsRoot -Recurse -Force
            Write-Host "Removed $projectsRoot" -ForegroundColor Green
        } else {
            Write-Host "Project purge skipped (confirmation not matched)." -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "Done. Machine state cleared." -ForegroundColor Green
Write-Host "ALSO clear the browser state, or the app reopens your last project and skips onboarding:" -ForegroundColor Cyan
Write-Host "  - Easiest: open the app in a fresh / InPrivate browser window, OR"
Write-Host "  - Clear site data (localStorage 'lastOpenedProjectPath') for the app's http://127.0.0.1:<port> origin."
