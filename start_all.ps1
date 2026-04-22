param(
    [string]$PythonExe = "",
    [string]$YoloPythonExe = "D:\Conda\envs\yolo\python.exe",
    [string]$MavenExe = "mvn",
    [string]$JavaExe = "java",
    [int]$Port = 8000,
    [int]$MaxPort = 8010,
    [int]$StartupTimeoutSeconds = 20,
    [switch]$EnableExternalExcel = $false,
    [switch]$WaitForReady = $false,
    [switch]$EnableReload = $false
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunDir = Join-Path $RootDir ".run"
$LogDir = Join-Path $RunDir "logs"
$PidFile = Join-Path $RunDir "services.json"
$TraceFile = Join-Path $RunDir "start_trace.log"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Set-Content -LiteralPath $TraceFile -Value "" -Encoding UTF8

function Test-CommandAvailable {
    param([string]$CommandName)
    if ([string]::IsNullOrWhiteSpace($CommandName)) {
        return $false
    }
    if (Test-Path -LiteralPath $CommandName) {
        return $true
    }
    return $null -ne (Get-Command $CommandName -ErrorAction SilentlyContinue)
}

function Write-TraceStep {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date).ToString("HH:mm:ss.fff"), $Message
    Add-Content -LiteralPath $TraceFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Normalize-PythonExe {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Value
    }
    $v = $Value.Trim()
    $v = $v -replace "^\uFEFF", ""
    # Strip accidental localized prefixes like "错误:" if the rest looks like a Windows absolute path.
    if ($v -match "^[^A-Za-z]{1,8}:[\\\/].+$" -and $v -match "[A-Za-z]:[\\\/].+$") {
        $v = [regex]::Match($v, "[A-Za-z]:[\\\/].+$").Value
    }
    return $v
}

function Wait-ServiceReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds([Math]::Max(3, $TimeoutSeconds))
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 2 -UseBasicParsing
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 400
        }
    }
    return $false
}

function Get-AvailablePort {
    param(
        [int]$StartPort,
        [int]$EndPort
    )
    for ($p = $StartPort; $p -le $EndPort; $p++) {
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
            $listener.Start()
            return $p
        }
        catch {
            continue
        }
        finally {
            if ($listener) {
                try { $listener.Stop() } catch {}
            }
        }
    }
    throw "No available port in range $StartPort-$EndPort."
}

function Test-PortListeningByPid {
    param(
        [int]$Port,
        [int]$ProcId
    )
    $lines = netstat -ano -p tcp | Select-String (":" + $Port + "\s+.*LISTENING\s+" + $ProcId + "$")
    return $null -ne $lines
}

Write-TraceStep "Script start."

$PythonExe = Normalize-PythonExe -Value $PythonExe

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    if (Test-Path -LiteralPath $YoloPythonExe) {
        $PythonExe = $YoloPythonExe
    }
    elseif (Test-CommandAvailable -CommandName "python") {
        $PythonExe = "python"
    }
    else {
        throw "YOLO python not found: $YoloPythonExe, and fallback 'python' not found. Please set -PythonExe explicitly."
    }
}
$PythonExe = Normalize-PythonExe -Value $PythonExe
Write-TraceStep "Python resolved: $PythonExe"

if (-not (Test-CommandAvailable -CommandName $PythonExe)) {
    throw "Python command not found: $PythonExe"
}
Write-TraceStep "Python command check passed."

$hasMaven = Test-CommandAvailable -CommandName $MavenExe
$hasJava = Test-CommandAvailable -CommandName $JavaExe
Write-TraceStep "Command checks done. hasMaven=$hasMaven hasJava=$hasJava"

$targetDir = Join-Path $RootDir "checkinexcel\target"
$jarFile = Get-ChildItem -LiteralPath $targetDir -Filter "*.jar" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notmatch "original" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$excelStartMode = "builtin"
if ($EnableExternalExcel) {
    if ($hasMaven) {
        $excelStartMode = "maven"
    }
    elseif ($hasJava -and $jarFile) {
        $excelStartMode = "jar"
    }
}
Write-TraceStep "Excel mode selected: $excelStartMode"

if (Test-Path -LiteralPath $PidFile) {
    try {
        $oldStatus = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
        $alive = @()
        foreach ($pid in @($oldStatus.fastapi_pid, $oldStatus.excel_pid)) {
            if ($pid -and (Get-Process -Id $pid -ErrorAction SilentlyContinue)) {
                $alive += [string]$pid
            }
        }
        if ($alive.Count -gt 0) {
            Write-Warning ("Existing service process(es) are still running: " + ($alive -join ", "))
            Write-Warning "Run .\stop_all.ps1 first if you want to restart."
            exit 1
        }
    }
    catch {
        Write-Warning "Failed to parse old PID file. Continue with a fresh start."
    }
}
Write-TraceStep "PID file check complete."

$InitialPort = Get-AvailablePort -StartPort $Port -EndPort $MaxPort
Write-TraceStep "Initial available port candidate: $InitialPort"

$RunId = Get-Date -Format "yyyyMMdd_HHmmss"
$ExcelOut = Join-Path $LogDir ("excel." + $RunId + ".out.log")
$ExcelErr = Join-Path $LogDir ("excel." + $RunId + ".err.log")
Write-TraceStep "Log files prepared. RunId=$RunId"

$SelectedPort = $null
$FastApiOut = $null
$FastApiErr = $null
$fastApiProc = $null

for ($candidate = $InitialPort; $candidate -le $MaxPort; $candidate++) {
    $candidateOut = Join-Path $LogDir ("fastapi." + $RunId + ".p" + $candidate + ".out.log")
    $candidateErr = Join-Path $LogDir ("fastapi." + $RunId + ".p" + $candidate + ".err.log")
    $fastApiArgs = @(
        "-m", "uvicorn", "api:app",
        "--host", "0.0.0.0",
        "--port", [string]$candidate
    )
    if ($EnableReload) {
        $fastApiArgs += "--reload"
    }
    Write-TraceStep ("FastAPI start attempt on port " + $candidate + " args: " + ($fastApiArgs -join " "))

    $probeProc = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $fastApiArgs `
        -WorkingDirectory $RootDir `
        -RedirectStandardOutput $candidateOut `
        -RedirectStandardError $candidateErr `
        -PassThru

    $ready = $false
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 500
        if ($probeProc.HasExited) {
            break
        }
        if (Test-PortListeningByPid -Port $candidate -ProcId $probeProc.Id) {
            $ready = $true
            break
        }
    }

    if ($probeProc.HasExited -or -not $ready) {
        if (-not $probeProc.HasExited) {
            Stop-Process -Id $probeProc.Id -Force -ErrorAction SilentlyContinue
        }
        Write-TraceStep "FastAPI process not ready on port $candidate. Trying next port."
        continue
    }

    $SelectedPort = $candidate
    $FastApiOut = $candidateOut
    $FastApiErr = $candidateErr
    $fastApiProc = $probeProc
    break
}

if (-not $fastApiProc) {
    throw "FastAPI failed to start on any port in range $InitialPort-$MaxPort."
}
Write-TraceStep "FastAPI process started. PID=$($fastApiProc.Id) port=$SelectedPort"

$excelFilePath = $null
$excelArgs = @()

if ($excelStartMode -eq "maven") {
    $excelFilePath = $MavenExe
    $excelArgs = @(
        "-f", (Join-Path $RootDir "checkinexcel\pom.xml"),
        "spring-boot:run"
    )
}
else {
    $excelFilePath = $JavaExe
    $excelArgs = @("-jar", $jarFile.FullName)
}

Write-TraceStep "FastAPI process alive after initial check."
if ($WaitForReady) {
    if (-not (Wait-ServiceReady -Url ("http://127.0.0.1:" + $SelectedPort + "/docs") -TimeoutSeconds $StartupTimeoutSeconds)) {
        Stop-Process -Id $fastApiProc.Id -Force -ErrorAction SilentlyContinue
        throw "FastAPI startup timeout (${StartupTimeoutSeconds}s). Process stopped automatically."
    }
}

$excelProc = $null
if ($excelStartMode -ne "builtin") {
    $excelProc = Start-Process `
        -FilePath $excelFilePath `
        -ArgumentList $excelArgs `
        -WorkingDirectory $RootDir `
        -RedirectStandardOutput $ExcelOut `
        -RedirectStandardError $ExcelErr `
        -PassThru

    Start-Sleep -Seconds 1
    if ($excelProc.HasExited) {
        $excelProc = $null
        $excelStartMode = "builtin"
        Write-Warning "External checkinexcel failed to start, switched to builtin Excel API on port 8000."
    }
    elseif ($WaitForReady) {
        if (-not (Wait-ServiceReady -Url "http://127.0.0.1:8080" -TimeoutSeconds $StartupTimeoutSeconds)) {
            Stop-Process -Id $excelProc.Id -Force -ErrorAction SilentlyContinue
            $excelProc = $null
            $excelStartMode = "builtin"
            Write-Warning "External checkinexcel startup timeout. Switched to builtin Excel API on port 8000."
        }
    }
}
Write-TraceStep "Excel mode init complete. mode=$excelStartMode"

$excelApiUrl = "http://localhost:8000/api/excel/generate"
$baseUrl = "http://localhost:$SelectedPort"
$homeUrl = "$baseUrl/"
$checkinUrl = "$baseUrl/checkin-ui"
$analysisUrl = "$baseUrl/analysis-ui"
$docsUrl = "$baseUrl/docs"

if ($excelStartMode -eq "builtin") {
    $excelApiUrl = "$baseUrl/api/excel/generate"
}
if ($excelStartMode -ne "builtin") {
    $excelApiUrl = "http://localhost:8080/api/excel/generate"
}

$status = [ordered]@{
    started_at      = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    python_exe      = $PythonExe
    fastapi_pid     = $fastApiProc.Id
    excel_pid       = if ($excelProc) { $excelProc.Id } else { $null }
    excel_mode      = $excelStartMode
    port            = $SelectedPort
    home_url        = $homeUrl
    checkin_url     = $checkinUrl
    analysis_url    = $analysisUrl
    docs_url        = $docsUrl
    excel_api_url   = $excelApiUrl
    fastapi_out_log = $FastApiOut
    fastapi_err_log = $FastApiErr
    excel_out_log   = $ExcelOut
    excel_err_log   = $ExcelErr
}

$status | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8
Write-TraceStep "Status file written: $PidFile"

Write-Host ""
Write-Host "Services started:"
Write-Host "Python: $PythonExe"
Write-Host "1) FastAPI (PID=$($fastApiProc.Id)): $baseUrl"
if ($excelStartMode -eq "builtin") {
    Write-Host "2) Excel API mode: builtin (served by FastAPI on $excelApiUrl)"
}
else {
    Write-Host "2) checkinexcel (PID=$($excelProc.Id)): http://localhost:8080"
}
Write-Host ""
Write-Host "Home: $homeUrl"
Write-Host "Stop: .\stop_all.ps1"
Write-Host "Logs: $LogDir"
Write-TraceStep "Script end."
