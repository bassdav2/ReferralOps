$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RootDir

$BackendUrl = if ($env:BACKEND_URL) { $env:BACKEND_URL } else { "http://127.0.0.1:8000" }
$FrontendUrl = if ($env:FRONTEND_URL) { $env:FRONTEND_URL } else { "http://127.0.0.1:5173" }
$BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 8000 }
$FrontendPort = if ($env:FRONTEND_PORT) { [int]$env:FRONTEND_PORT } else { 5173 }
$LogDir = if ($env:LOG_DIR) { $env:LOG_DIR } else { Join-Path $RootDir "tmp\judge-demo" }
$OpenBrowser = if ($env:OPEN_BROWSER) { $env:OPEN_BROWSER } else { "true" }
$env:NO_EXTERNAL_AI_CALLS = "true"
if (-not $env:BACKEND_CORS_ORIGINS) {
  $CorsOrigins = @(
    $FrontendUrl,
    "http://localhost:$FrontendPort",
    "http://127.0.0.1:$FrontendPort"
  ) | Select-Object -Unique
  $env:BACKEND_CORS_ORIGINS = $CorsOrigins -join ","
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Fail($Message) {
  Write-Host ""
  Write-Host "ERROR: $Message" -ForegroundColor Red
  exit 1
}

function Confirm-Install($Message) {
  if ($env:INSTALL_SYSTEM_DEPS -match "^(1|true|yes)$") {
    return $true
  }
  if ($env:INSTALL_SYSTEM_DEPS -match "^(0|false|no)$") {
    return $false
  }

  $Answer = Read-Host "$Message [y/N]"
  return $Answer -match "^(y|yes)$"
}

function Write-ManualInstallHint {
  Write-Host ""
  Write-Host "Manual Windows install command:"
  Write-Host "  winget install -e --id Python.Python.3.12; winget install -e --id OpenJS.NodeJS.LTS; winget install -e --id UB-Mannheim.TesseractOCR"
  Write-Host ""
}

function Update-PathFromRegistry {
  $MachinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$MachinePath;$UserPath"

  $CommonPaths = @(
    (Join-Path $env:ProgramFiles "nodejs"),
    (Join-Path $env:ProgramFiles "Tesseract-OCR"),
    (Join-Path $env:LocalAppData "Microsoft\WindowsApps")
  )

  foreach ($PathEntry in $CommonPaths) {
    if ((Test-Path $PathEntry) -and ($env:Path -notlike "*$PathEntry*")) {
      $env:Path = "$env:Path;$PathEntry"
    }
  }
}

function Find-TesseractCommand {
  $Command = Get-Command tesseract.exe -ErrorAction SilentlyContinue
  if (-not $Command) {
    $Command = Get-Command tesseract -ErrorAction SilentlyContinue
  }
  if ($Command) {
    return $Command.Source
  }

  $ProgramFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
  $Candidates = @(
    (Join-Path $env:ProgramFiles "Tesseract-OCR\tesseract.exe"),
    $(if ($ProgramFilesX86) { Join-Path $ProgramFilesX86 "Tesseract-OCR\tesseract.exe" }),
    (Join-Path $env:LocalAppData "Programs\Tesseract-OCR\tesseract.exe"),
    "C:\ProgramData\chocolatey\bin\tesseract.exe"
  )

  foreach ($Candidate in $Candidates) {
    if ($Candidate -and (Test-Path $Candidate)) {
      return $Candidate
    }
  }

  return $null
}

function Set-TesseractEnvironment {
  Update-PathFromRegistry
  $TesseractCommand = Find-TesseractCommand
  if (-not $TesseractCommand) {
    return
  }

  $TesseractDir = Split-Path -Parent $TesseractCommand
  if ($env:Path -notlike "*$TesseractDir*") {
    $env:Path = "$env:Path;$TesseractDir"
  }
  $env:TESSERACT_CMD = $TesseractCommand

  $TessData = Join-Path $TesseractDir "tessdata"
  if ((Test-Path $TessData) -and (-not $env:TESSDATA_PREFIX)) {
    $env:TESSDATA_PREFIX = $TessData
  }
}

function Invoke-CommandParts($CommandParts, $Arguments) {
  $Parts = @($CommandParts)
  $Executable = $Parts[0]
  $PrefixArgs = @()
  if ($Parts.Count -gt 1) {
    $PrefixArgs = $Parts[1..($Parts.Count - 1)]
  }
  & $Executable @PrefixArgs @Arguments
}

function Test-PythonCandidate($Executable, $PrefixArgs) {
  try {
    & $Executable @PrefixArgs "scripts/check_runtime.py" *> $null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Resolve-PythonCommand([switch]$Quiet) {
  if ($env:PYTHON) {
    if (Test-PythonCandidate $env:PYTHON @()) {
      return @($env:PYTHON)
    }
  }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    if (Test-PythonCandidate "py" @("-3.12")) {
      return @("py", "-3.12")
    }
    if (Test-PythonCandidate "py" @("-3")) {
      return @("py", "-3")
    }
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    if (Test-PythonCandidate "python" @()) {
      return @("python")
    }
  }
  if (Get-Command python3 -ErrorAction SilentlyContinue) {
    if (Test-PythonCandidate "python3" @()) {
      return @("python3")
    }
  }
  if ($Quiet) {
    return $null
  }
  Fail "Python 3.12+ is required."
}

function Test-PythonRuntime {
  $CommandParts = Resolve-PythonCommand -Quiet
  if ($null -eq $CommandParts) {
    return $false
  }
  return @($CommandParts).Count -gt 0
}

function Test-NodeRuntime {
  if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    return $false
  }
  try {
    $Major = & node -p "Number(process.versions.node.split('.')[0])"
    return [int]$Major -ge 22
  } catch {
    return $false
  }
}

function Test-NodeToolchain {
  $NpmCommand = Get-Command npm -ErrorAction SilentlyContinue
  return (Test-NodeRuntime) -and ($null -ne $NpmCommand)
}

function Install-WingetPackage($Label, $PackageIds) {
  foreach ($PackageId in $PackageIds) {
    Write-Host ""
    Write-Host "Installing $Label with winget package $PackageId..."
    winget install --id $PackageId --exact --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) {
      return
    }
  }
  Fail "Could not install $Label with winget. Install it manually and rerun Start ReferralOps.cmd."
}

function Install-MissingSystemDependencies {
  $MissingRequired = @()
  $MissingOptional = @()

  if (-not (Test-PythonRuntime)) {
    $MissingRequired += "Python 3.12+"
  }
  if (-not (Test-NodeToolchain)) {
    $MissingRequired += "Node.js 22+ and npm"
  }
  if (-not (Find-TesseractCommand)) {
    $MissingOptional += "Tesseract OCR for scanned PDFs"
  }

  if (($MissingRequired.Count -eq 0) -and ($MissingOptional.Count -eq 0)) {
    return
  }

  Write-Host "Missing system dependencies:"
  foreach ($Dependency in $MissingRequired) {
    Write-Host "  - $Dependency"
  }
  foreach ($Dependency in $MissingOptional) {
    Write-Host "  - $Dependency"
  }
  Write-Host ""

  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-ManualInstallHint
    if ($MissingRequired.Count -gt 0) {
      Fail "winget is not available and required system dependencies are missing."
    }
    Write-Host "Warning: Tesseract is missing. Selectable PDFs work; scanned PDFs need OCR."
    return
  }

  if (Confirm-Install "Install missing system dependencies with winget now?") {
    if (-not (Test-PythonRuntime)) {
      Install-WingetPackage "Python 3.12" @("Python.Python.3.12")
    }
    if (-not (Test-NodeToolchain)) {
      Install-WingetPackage "Node.js LTS" @("OpenJS.NodeJS.LTS")
    }
    if (-not (Find-TesseractCommand)) {
      Install-WingetPackage "Tesseract OCR" @("UB-Mannheim.TesseractOCR", "tesseract-ocr.tesseract")
    }
    Update-PathFromRegistry
    Set-TesseractEnvironment
  } elseif ($MissingRequired.Count -gt 0) {
    Write-ManualInstallHint
    Fail "Required system dependencies are missing."
  }

  $StillMissingRequired = @()
  if (-not (Test-PythonRuntime)) {
    $StillMissingRequired += "Python 3.12+"
  }
  if (-not (Test-NodeToolchain)) {
    $StillMissingRequired += "Node.js 22+ and npm"
  }

  if ($StillMissingRequired.Count -gt 0) {
    Write-ManualInstallHint
    Fail "Some required dependencies are still missing after installation. Close this window and rerun Start ReferralOps.cmd after the installers finish."
  }

  if (-not (Find-TesseractCommand)) {
    Write-Host "Warning: Tesseract is still missing. Selectable PDFs work; scanned PDFs need OCR."
  }
}

function Test-Url($Url) {
  try {
    Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Test-PortInUse($Port) {
  try {
    $Connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
    return $Connections.Count -gt 0
  } catch {
    try {
      $Client = [System.Net.Sockets.TcpClient]::new()
      $Task = $Client.ConnectAsync("127.0.0.1", $Port)
      $Connected = $Task.Wait(200)
      $Client.Close()
      return $Connected
    } catch {
      return $false
    }
  }
}

function Wait-ForUrl($Label, $Url, $LogFile, $ErrorLogFile) {
  for ($Index = 0; $Index -lt 90; $Index += 1) {
    if (Test-Url $Url) {
      Write-Host "$Label ready: $Url"
      return
    }
    Start-Sleep -Seconds 1
  }

  Write-Error "$Label did not become ready. Last log lines:"
  if (Test-Path $LogFile) {
    Get-Content -Path $LogFile -Tail 80 -ErrorAction SilentlyContinue
  }
  if (Test-Path $ErrorLogFile) {
    Get-Content -Path $ErrorLogFile -Tail 80 -ErrorAction SilentlyContinue
  }
  exit 1
}

function Resolve-NpmPath {
  $NpmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if (-not $NpmCommand) {
    $NpmCommand = Get-Command npm -ErrorAction SilentlyContinue
  }
  if (-not $NpmCommand) {
    Fail "Missing required command: npm"
  }
  return $NpmCommand.Source
}

Set-TesseractEnvironment
Install-MissingSystemDependencies
Set-TesseractEnvironment

$PythonCommand = Resolve-PythonCommand
Invoke-CommandParts $PythonCommand @("scripts/check_runtime.py")
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

if (-not (Find-TesseractCommand)) {
  Write-Host "Warning: Tesseract is not installed or not on PATH. Selectable PDFs still work; scanned PDFs need OCR."
}

if (-not (Test-Path ".env")) {
  Copy-Item ".env.local-model.example" ".env"
  Write-Host "Created .env from .env.local-model.example"
}

$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
$VenvPip = Join-Path $RootDir ".venv\Scripts\pip.exe"
$VenvUvicorn = Join-Path $RootDir ".venv\Scripts\uvicorn.exe"
$FrontendNodeModules = Join-Path $RootDir "frontend\node_modules"
$NpmPath = Resolve-NpmPath

if ((-not (Test-Path $VenvPython)) -or (-not (Test-Path $VenvUvicorn)) -or (-not (Test-Path $FrontendNodeModules))) {
  Write-Host "Installing local dependencies..."
  Invoke-CommandParts $PythonCommand @("-m", "venv", ".venv")
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
  & $VenvPython -m pip install --upgrade pip
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
  & $VenvPip install -e ".[dev]"
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
  & $NpmPath --prefix frontend ci
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
} else {
  Write-Host "Local dependencies already installed."
}

Write-Host "Preparing synthetic guideline demo data..."
& $VenvPython scripts/ingest_guidelines.py
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

$BackendHealth = "$BackendUrl/api/health"
$BackendLog = Join-Path $LogDir "backend.log"
$BackendErrorLog = Join-Path $LogDir "backend.err.log"
$FrontendLog = Join-Path $LogDir "frontend.log"
$FrontendErrorLog = Join-Path $LogDir "frontend.err.log"

if (Test-Url $BackendHealth) {
  Write-Host "Backend already running: $BackendHealth"
} elseif (Test-PortInUse $BackendPort) {
  Fail "Port $BackendPort is in use, but $BackendHealth is not healthy."
} else {
  Write-Host "Starting backend on $BackendUrl..."
  $BackendProcess = Start-Process -FilePath $VenvUvicorn `
    -ArgumentList @("backend.app.main:app", "--host", "0.0.0.0", "--port", "$BackendPort", "--reload") `
    -WorkingDirectory $RootDir `
    -RedirectStandardOutput $BackendLog `
    -RedirectStandardError $BackendErrorLog `
    -PassThru
  $BackendProcess.Id | Set-Content (Join-Path $LogDir "backend.pid")
  Wait-ForUrl "Backend" $BackendHealth $BackendLog $BackendErrorLog
}

if (Test-Url $FrontendUrl) {
  Write-Host "Frontend already running: $FrontendUrl"
} elseif (Test-PortInUse $FrontendPort) {
  Fail "Port $FrontendPort is in use, but $FrontendUrl is not reachable."
} else {
  Write-Host "Starting frontend on $FrontendUrl..."
  $FrontendProcess = Start-Process -FilePath $NpmPath `
    -ArgumentList @("--prefix", "frontend", "run", "dev", "--", "--host", "0.0.0.0") `
    -WorkingDirectory $RootDir `
    -RedirectStandardOutput $FrontendLog `
    -RedirectStandardError $FrontendErrorLog `
    -PassThru
  $FrontendProcess.Id | Set-Content (Join-Path $LogDir "frontend.pid")
  Wait-ForUrl "Frontend" $FrontendUrl $FrontendLog $FrontendErrorLog
}

if ($OpenBrowser -eq "true") {
  Start-Process $FrontendUrl
}

Write-Host ""
Write-Host "ReferralOps judge demo is ready."
Write-Host ""
Write-Host "Dashboard: $FrontendUrl"
Write-Host "Backend:   $BackendHealth"
Write-Host "Logs:      $LogDir"
Write-Host ""
Write-Host "In the dashboard:"
Write-Host "1. Open Local Model."
Write-Host "2. Enter your local OpenAI-compatible endpoint and model id."
Write-Host "3. Click Test connection."
Write-Host "4. Drag PDFs from demos/referral_inbox_samples/ into PDF-Inbox."
Write-Host ""
Write-Host "To stop servers started by this launcher:"
Write-Host "  Stop-Process -Id (Get-Content `"$LogDir\*.pid`")"
