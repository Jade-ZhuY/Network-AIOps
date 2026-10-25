$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$manifest=Join-Path $root 'java-backend\.local\run.json'
if(-not (Test-Path -LiteralPath $manifest)){throw 'No Java process manifest found; nothing was stopped.'}
$run=Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
$allowedJars=@(
    [IO.Path]::GetFullPath((Join-Path $root 'java-backend\aiops-startup\target\aiops-startup-0.1.0.jar')),
    [IO.Path]::GetFullPath((Join-Path $root 'java-backend\target\aiops-business-0.1.0.jar'))
)
# Accept the previous layout only for stopping this project's already-running old process.
$expectedJar=[IO.Path]::GetFullPath($run.jar)
if($expectedJar -notin $allowedJars){throw 'Unexpected JAR path; nothing was stopped.'}
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$run.pid)" -ErrorAction SilentlyContinue
if(-not $process){Write-Output 'The recorded Java process is already stopped.';exit 0}
if($process.Name -ne 'java.exe' -or -not $process.CommandLine.Contains($expectedJar)){throw 'PID no longer matches this project; nothing was stopped.'}
Stop-Process -Id ([int]$run.pid) -ErrorAction Stop
Wait-Process -Id ([int]$run.pid) -Timeout 15 -ErrorAction SilentlyContinue
Write-Output 'Stopped only the Java process recorded for this project. This is a Windows development-process stop, not a production service manager.'
