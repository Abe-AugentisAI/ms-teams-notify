# teams-notify installer (Windows PowerShell)
$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "==> teams-notify: installing from $RepoDir"

$Py = "python"
# Get-Command alone is satisfied by the Microsoft Store's python stub, so probe a real
# run; the same probe enforces the Python >= 3.8 floor python-dotenv requires.
$PyOk = $false
try {
    & $Py -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
    $PyOk = ($LASTEXITCODE -eq 0)
} catch {}
if (-not $PyOk) {
    throw "'python' is missing, a Store stub, or older than 3.8. Install Python 3.8+ and re-run."
}

Write-Host "==> Creating virtual environment (.venv)"
& $Py -m venv "$RepoDir\.venv"
$VenvPy = "$RepoDir\.venv\Scripts\python.exe"
$Script = "$RepoDir\src\teams_notify.py"
& $VenvPy -m pip install --quiet --upgrade pip
& $VenvPy -m pip install --quiet -r "$RepoDir\requirements.txt"

Write-Host "==> Installing the 'teams' command on PATH"
$BinDir = "$HOME\.local\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
# Windows has no usable equivalent of the bash wrapper's symlink resolution, so shim it.
# OEM encoding, not ASCII: cmd.exe reads the OEM code page, and ASCII mangles any
# non-ASCII characters in the profile path to '?'.
@"
@echo off
"$VenvPy" "$Script" %*
"@ | Set-Content -Path "$BinDir\teams.cmd" -Encoding OEM
# Git Bash — what Claude Code's Bash tool uses on Windows — resolves bare 'teams' to an
# extensionless file, never to teams.cmd, and SKILL.md's allowed-tools match the bare
# name. LF endings and forward slashes on purpose: sh chokes on CRLF shebangs.
$ShimBody = "#!/bin/sh`nexec `"$($VenvPy -replace '\\','/')`" `"$($Script -replace '\\','/')`" `"`$@`"`n"
[IO.File]::WriteAllText("$BinDir\teams", $ShimBody)
if (($env:PATH -split ';') -notcontains $BinDir) {
    Write-Host "    [warn] $BinDir is not on PATH — add it"
}

Write-Host "==> Installing the global /teams skill"
# Copied rather than symlinked: symlinks need Developer Mode or admin on Windows. That
# means a Windows clone must re-run this installer after 'git pull'; the POSIX install
# symlinks instead and needs no reinstall.
$SkillDir = "$HOME\.claude\skills\teams"
New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
Copy-Item "$RepoDir\skills\teams\SKILL.md" "$SkillDir\SKILL.md" -Force

Write-Host "==> Installing the cross-agent skill (~\.agents\skills)"
# agentskills.io cross-client convention — read by Codex, Gemini CLI, Cursor, Copilot,
# Amp, Goose, and others. Copied, same as the Claude install above.
$AgentsSkillDir = "$HOME\.agents\skills\teams"
New-Item -ItemType Directory -Force -Path $AgentsSkillDir | Out-Null
Copy-Item "$RepoDir\skills\teams\SKILL.md" "$AgentsSkillDir\SKILL.md" -Force

Write-Host "==> Installing the Antigravity skill (~\.gemini\config\skills)"
# Antigravity's global skills path, mirrored from the documented POSIX location
# (~/.gemini/config/skills); its .agents/skills support is workspace-level only.
$GeminiSkillDir = "$HOME\.gemini\config\skills\teams"
New-Item -ItemType Directory -Force -Path $GeminiSkillDir | Out-Null
Copy-Item "$RepoDir\skills\teams\SKILL.md" "$GeminiSkillDir\SKILL.md" -Force

# Retire the pre-symlink slash command; two entries named 'teams' would shadow each other.
if (Test-Path "$HOME\.claude\commands\teams.md") {
    Remove-Item "$HOME\.claude\commands\teams.md" -Force
    Write-Host "    removed obsolete ~/.claude/commands/teams.md (superseded by the skill)"
}

Write-Host "==> Preparing .env"
if (-not (Test-Path "$RepoDir\.env")) {
    Copy-Item "$RepoDir\.env.example" "$RepoDir\.env"
    Write-Host "    created $RepoDir\.env  (fill in your values)"
} else {
    Write-Host "    $RepoDir\.env already exists — left untouched"
}

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  1. Edit $RepoDir\.env with your Teams webhook + Graph app values."
Write-Host "  2. Test:  $VenvPy $Script --target channel --title `"Install check`" --status success"
Write-Host "  3. In Claude Code (any project):  /teams channel `"Install check`" success"
