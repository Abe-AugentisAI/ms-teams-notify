# teams-notify installer (Windows PowerShell)
$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "==> teams-notify: installing from $RepoDir"

$Py = "python"
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) {
    throw "'python' not found. Install Python 3 and re-run."
}

Write-Host "==> Creating virtual environment (.venv)"
& $Py -m venv "$RepoDir\.venv"
$VenvPy = "$RepoDir\.venv\Scripts\python.exe"
& $VenvPy -m pip install --quiet --upgrade pip
& $VenvPy -m pip install --quiet -r "$RepoDir\requirements.txt"

Write-Host "==> Installing the /teams slash command"
$CmdDir = "$HOME\.claude\commands"
New-Item -ItemType Directory -Force -Path $CmdDir | Out-Null
$Script = "$RepoDir\src\teams_notify.py"
$tpl = Get-Content "$RepoDir\commands\teams.md" -Raw
$tpl = $tpl.Replace('__VENV_PY__', $VenvPy).Replace('__SCRIPT__', $Script)
Set-Content -Path "$CmdDir\teams.md" -Value $tpl -Encoding UTF8

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
