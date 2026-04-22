$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $RootDir ".run\services.json"
$KnownPorts = @(8000,8001,8002,8003,8004,8005,8006,8007,8008,8009,8010,8080)

function Stop-ProjectPortListeners {
    param([int[]]$Ports)
    $killed = @()
    foreach ($port in $Ports) {
        $matches = netstat -ano -p tcp | Select-String (":" + $port + "\s+.*LISTENING\s+(\d+)$")
        if (-not $matches) {
            continue
        }
        foreach ($m in $matches) {
            $text = $m.ToString().Trim()
            $pidText = ($text -split "\s+")[-1]
            if (-not ($pidText -match "^\d+$")) {
                continue
            }
            $procId = [int]$pidText
            if ($procId -le 0 -or $procId -eq $PID) {
                continue
            }
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if (-not $proc) {
                continue
            }
            $name = ($proc.ProcessName | ForEach-Object { $_.ToLowerInvariant() })
            if ($name -in @("python", "python3", "java", "mvn", "powershell", "pwsh")) {
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                $killed += "port=$port pid=$procId name=$name"
            }
        }
    }
    if ($killed.Count -gt 0) {
        Write-Host "Port cleanup killed:"
        $killed | ForEach-Object { Write-Host "  $_" }
    }
}

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host "No PID file found. Nothing to stop."
    Stop-ProjectPortListeners -Ports $KnownPorts
    exit 0
}

try {
    $status = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
}
catch {
    Write-Warning "PID file is invalid. Stop related processes manually."
    exit 1
}

$targets = @(
    @{ Name = "FastAPI"; PID = $status.fastapi_pid },
    @{ Name = "checkinexcel"; PID = $status.excel_pid }
)

foreach ($item in $targets) {
    $procId = [int]($item.PID)
    if (-not $procId) {
        continue
    }

    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "$($item.Name): process not found (PID=$procId)"
        continue
    }

    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300

    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
        Write-Warning "$($item.Name): failed to stop (PID=$procId)"
    }
    else {
        Write-Host "$($item.Name): stopped (PID=$procId)"
    }
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Stop-ProjectPortListeners -Ports $KnownPorts
Write-Host "Stop completed."
