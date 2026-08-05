# One-click installer for codex-vision-proxy (Windows)
#
# Automates the steps in AGENT_INSTALL.md on Windows:
#   locate/backup Codex config -> prepare install dir + vision env -> start proxy
#   -> repoint base_url -> catalog modality -> Startup entry -> verify
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Port 19100] [-NonInteractive] [-NoStart] [-NoVerify]
#
# Env overrides: VISION_API_KEY VISION_BASE_URL VISION_MODEL LANG CODEX_HOME INSTALL_DIR ENV_FILE

param(
  [int]$Port = 19100,
  [switch]$NonInteractive,
  [switch]$NoStart,
  [switch]$NoVerify
)

$ErrorActionPreference = "Stop"

function Log($m)  { Write-Host "[install] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[warn] $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "[error] $m" -ForegroundColor Red; exit 1 }

# ---------- 0. prerequisites ----------
$py = $null
foreach ($cand in @("py -3", "python3", "python")) {
  $cmd = ($cand -split " ")[0]
  if (Get-Command $cmd -ErrorAction SilentlyContinue) { $py = $cand; break }
}
if (-not $py) { Die "Python 3.11+ not found (py launcher or python on PATH required)" }

& $py -c "import sys, tomllib; assert sys.version_info >= (3, 11)" 2>$null
if ($LASTEXITCODE -ne 0) { Die "Python 3.11+ required (tomllib); run: py -3 --version" }

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path "$RepoDir\codex-vision-proxy.py")) { Die "codex-vision-proxy.py not found next to install.ps1" }

# ---------- 1. locate Codex config ----------
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
$Config = Join-Path $CodexHome "config.toml"
if (-not (Test-Path $Config)) { Die "Codex config not found at $Config (set CODEX_HOME if custom)" }

# ---------- parse config via embedded python ----------
$PyParse = @'
import sys, tomllib, pathlib, json
config_path, codex_home = sys.argv[1], sys.argv[2]
with open(config_path, "rb") as f:
    cfg = tomllib.load(f)
provider = cfg.get("model_provider") or ""
model = cfg.get("model") or ""
upstream = ""
if provider:
    p = (cfg.get("model_providers") or {}).get(provider, {})
    upstream = p.get("base_url") or ""
catalog = cfg.get("model_catalog_json") or ""
if catalog and not pathlib.Path(catalog).is_absolute():
    catalog = str(pathlib.Path(codex_home) / catalog)
print(json.dumps({"provider": provider, "model": model, "upstream": upstream, "catalog": catalog}))
'@
$Parsed = & $py -c $PyParse $Config $CodexHome | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { Die "Could not parse $Config" }
if (-not $Parsed.provider -or -not $Parsed.model) { Die "Could not read model_provider/model from $Config" }
if (-not $Parsed.upstream) { Die "Could not read base_url for provider '$($Parsed.provider)'" }
if ($Parsed.upstream -like "*127.0.0.1:$Port*" -or $Parsed.upstream -like "*localhost:$Port*") {
  Die "Codex already points at $($Parsed.upstream) — cannot discover the real upstream. Restore from a backup first."
}
Log "Provider: $($Parsed.provider) | model: $($Parsed.model) | upstream: $($Parsed.upstream)"

# ---------- backups ----------
$Ts = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item $Config "$Config.vision-proxy.bak.$Ts"
Log "Backed up $Config -> $Config.vision-proxy.bak.$Ts"
if ($Parsed.catalog -and (Test-Path $Parsed.catalog)) {
  Copy-Item $Parsed.catalog "$($Parsed.catalog).vision-proxy.bak.$Ts"
  Log "Backed up catalog -> $($Parsed.catalog).vision-proxy.bak.$Ts"
}

# ---------- 2. install dir + vision env ----------
$InstallDir = if ($env:INSTALL_DIR) { $env:INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "codex-vision-proxy" }
$EnvFile    = if ($env:ENV_FILE)    { $env:ENV_FILE }    else { Join-Path $InstallDir "env" }
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item "$RepoDir\codex-vision-proxy.py" $InstallDir -Force
Copy-Item "$RepoDir\vision_client.py" $InstallDir -Force
if (-not (Test-Path $EnvFile)) { Copy-Item "$RepoDir\.env.example" $EnvFile }

function Get-EnvVal($name) {
  $line = Select-String -Path $EnvFile -Pattern "^$name=" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($line) { return ($line.Line -split "=", 2)[1].Trim('"') }
  return ""
}

$VisionKey  = if ($env:VISION_API_KEY)  { $env:VISION_API_KEY }  else { Get-EnvVal "VISION_API_KEY" }
$VisionBase = if ($env:VISION_BASE_URL) { $env:VISION_BASE_URL } else { Get-EnvVal "VISION_BASE_URL" }
if (-not $VisionBase) { $VisionBase = "https://api.inferera.com/v1" }
$VisionModel = if ($env:VISION_MODEL) { $env:VISION_MODEL } else { Get-EnvVal "VISION_MODEL" }
if (-not $VisionModel) { $VisionModel = "gemini-3.6-flash" }
$LangOut = if ($env:LANG) { $env:LANG } else { Get-EnvVal "LANG" }
if (-not $LangOut) { $LangOut = "zh" }

if (-not $VisionKey) {
  if ($NonInteractive) { Die "VISION_API_KEY is not set (use -NonInteractive with VISION_API_KEY env)" }
  $VisionKey = Read-Host "Vision API key (for $VisionBase)"
  if (-not $VisionKey) { Die "API key required" }
}
@("VISION_API_KEY=$VisionKey", "VISION_BASE_URL=$VisionBase", "VISION_MODEL=$VisionModel", "LANG=$LangOut") | Set-Content $EnvFile
Log "Vision config written to $EnvFile"

# ---------- 3. start proxy ----------
$PidFile = Join-Path $InstallDir "proxy.pid"
if ($NoStart) {
  Log "Skipping proxy start (-NoStart)"
} else {
  $args = @("$InstallDir\codex-vision-proxy.py", "--port", "$Port", "--upstream", $Parsed.upstream, "--env-file", $EnvFile, "--log", "$InstallDir\proxy.log")
  $p = Start-Process -FilePath ($py -split " ")[0] -ArgumentList $args -WindowStyle Hidden -PassThru
  $p.Id | Set-Content $PidFile
  Start-Sleep -Milliseconds 800
  if ($p.HasExited) {
    Warn "Proxy exited immediately — see $InstallDir\proxy.log (continuing with config changes anyway)"
  } else {
    Log "Proxy started (pid $($p.Id), port $Port)"
  }
}

# ---------- 4. repoint Codex base_url ----------
$PyPatch = @'
import re, sys
path, provider, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
text = open(path, encoding="utf-8").read()
pat = re.compile(r"(\[model_providers\." + re.escape(provider) + r"\][^\[]*?base_url\s*=\s*\")[^\"]*(\")", re.S)
new, n = pat.subn(r"\1http://127.0.0.1:%d\2" % port, text, count=1)
if n != 1:
    sys.exit("Could not locate base_url inside [model_providers.%s]" % provider)
open(path, "w", encoding="utf-8").write(new)
print("base_url -> http://127.0.0.1:%d for provider '%s'" % (port, provider))
'@
& $py -c $PyPatch $Config $Parsed.provider $Port
if ($LASTEXITCODE -ne 0) { Die "Failed to patch config.toml" }

# ---------- 5. catalog: add "image" modality ----------
if ($Parsed.catalog -and (Test-Path $Parsed.catalog)) {
  $PyCatalog = @'
import json, sys
path, model = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
models = data.get("models", data) if isinstance(data, dict) else data
entries = models if isinstance(models, list) else models.get("models", [])
target = None
for e in entries:
    if isinstance(e, dict) and (e.get("slug") == model or e.get("name") == model or e.get("id") == model):
        target = e
        break
if target is None:
    sys.exit("catalog entry for model '%s' not found (skipped)" % model)
mods = target.get("input_modalities")
if mods == ["text"]:
    target["input_modalities"] = ["text", "image"]
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("catalog: input_modalities -> [text, image] for '%s'" % model)
elif isinstance(mods, list) and "image" in mods:
    print("catalog: already supports image (no change)")
else:
    print("catalog: input_modalities = %s (left untouched)" % (mods or "unset"))
'@
  & $py -c $PyCatalog $Parsed.catalog $Parsed.model
} else {
  Warn "No model catalog file found — skipping modality edit. If Codex rejects view_image, see AGENT_INSTALL.md troubleshooting."
}

# ---------- 6. Startup entry ----------
if (-not $NoStart) {
  $Startup = [Environment]::GetFolderPath("Startup")
  $CmdPath = Join-Path $Startup "codex-vision-proxy.cmd"
  $cmd = "@echo off`r`nstart `"Codex Vision Proxy`" /min $py `"$InstallDir\codex-vision-proxy.py`" --port $Port --upstream `"$($Parsed.upstream)`" --env-file `"$EnvFile`" --log `"$InstallDir\proxy.log`""
  Set-Content -Path $CmdPath -Value $cmd -Encoding ASCII
  Log "Startup entry created: $CmdPath"
  & $CmdPath
  Start-Sleep -Milliseconds 800
}

# ---------- 7. verify ----------
if ($NoVerify) {
  Log "Skipping verification (-NoVerify)"
} else {
  & $py -m py_compile "$InstallDir\codex-vision-proxy.py" "$InstallDir\vision_client.py"
  if ($LASTEXITCODE -eq 0) { Log "py_compile OK" }
  $tcp = New-Object System.Net.Sockets.TcpClient
  try {
    $tcp.Connect("127.0.0.1", $Port)
    Log "Port $Port is listening"
  } catch {
    Warn "Port $Port not listening yet — check $InstallDir\proxy.log"
  } finally {
    $tcp.Close()
  }
}

Log "Done. Fully restart Codex, then ask your DeepSeek model to view_image a local image."
Log "Backups: $Config.vision-proxy.bak.$Ts"
if ($Parsed.catalog -and (Test-Path $Parsed.catalog)) { Log "Catalog backup: $($Parsed.catalog).vision-proxy.bak.$Ts" }
