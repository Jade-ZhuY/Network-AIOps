param(
    [switch]$Build,
    [ValidateRange(1024,65535)][int]$Port = 18081,
    [switch]$EnableAgent,
    [string]$AgentBaseUrl = 'http://127.0.0.1:8080'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $root 'java-backend'
$local = Join-Path $backend '.local'
$jar = Join-Path $backend 'aiops-startup\target\aiops-startup-0.1.0.jar'
New-Item -ItemType Directory -Path $local -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $backend 'data') -Force | Out-Null
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use. Existing services were not stopped."
}
if ($Build -or -not (Test-Path -LiteralPath $jar)) {
    Push-Location $backend
    try {
        & mvn -s .mvn/settings.xml -B -ntp verify
        if ($LASTEXITCODE -ne 0) { throw 'Java build/tests/format verification failed.' }
    } finally { Pop-Location }
}
$tokens = @{}
$environmentFile = Join-Path $root '.env'
if (Test-Path -LiteralPath $environmentFile) {
    foreach ($line in Get-Content -LiteralPath $environmentFile) {
        if ($line -match '^\s*(API_AUTH_TOKEN|API_ADMIN_TOKEN)\s*=\s*(.*)$') {
            $tokens[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
}
$credentialSource = 'root .env API tokens (read-only import)'
$tokenFile = Join-Path $local 'access-tokens.json'
if (-not $tokens.API_AUTH_TOKEN -or -not $tokens.API_ADMIN_TOKEN -or $tokens.API_AUTH_TOKEN.Length -lt 24 -or $tokens.API_ADMIN_TOKEN.Length -lt 24) {
    if (Test-Path -LiteralPath $tokenFile) {
        $saved = Get-Content -LiteralPath $tokenFile -Raw | ConvertFrom-Json
        $tokens.API_AUTH_TOKEN = $saved.engineer
        $tokens.API_ADMIN_TOKEN = $saved.admin
    } else {
        $tokens.API_AUTH_TOKEN = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).TrimEnd('=').Replace('+','-').Replace('/','_')
        $tokens.API_ADMIN_TOKEN = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).TrimEnd('=').Replace('+','-').Replace('/','_')
    }
    $credentialSource = 'independent local Java credentials (not Python authentication)'
}
if ($tokens.API_AUTH_TOKEN -eq $tokens.API_ADMIN_TOKEN) { throw 'Engineer and admin tokens must be distinct.' }
@{ engineer=$tokens.API_AUTH_TOKEN; admin=$tokens.API_ADMIN_TOKEN; source=$credentialSource } | ConvertTo-Json | Set-Content -LiteralPath $tokenFile -Encoding utf8
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $tokenFile /inheritance:r /grant:r "${account}:(F)" 'SYSTEM:(F)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict access to the local credential file.' }
$values = @{
    AIOPS_JAVA_AUTH_ENGINEER_TOKEN=$tokens.API_AUTH_TOKEN
    AIOPS_JAVA_AUTH_ADMIN_TOKEN=$tokens.API_ADMIN_TOKEN
    AIOPS_JAVA_PORT=[string]$Port
    AIOPS_AGENT_ENABLED=([bool]$EnableAgent).ToString().ToLowerInvariant()
    AIOPS_AGENT_BASE_URL=$AgentBaseUrl
    AIOPS_FRONTEND_PATH=(Join-Path $root 'app\web\dist')
}
$previous=@{}
try {
    foreach ($key in $values.Keys) { $previous[$key]=[Environment]::GetEnvironmentVariable($key,'Process'); [Environment]::SetEnvironmentVariable($key,$values[$key],'Process') }
    $java=(Get-Command java -ErrorAction Stop).Source
    $process=Start-Process -FilePath $java -ArgumentList @('-Xms128m','-Xmx768m','-Dfile.encoding=UTF-8','-jar',('"'+$jar+'"')) -WorkingDirectory $backend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $local 'stdout.log') -RedirectStandardError (Join-Path $local 'stderr.log') -PassThru
} finally {
    foreach ($key in $values.Keys) { [Environment]::SetEnvironmentVariable($key,$previous[$key],'Process') }
}
@{ pid=$process.Id; port=$Port; jar=$jar; started_at=[DateTimeOffset]::Now.ToString('o'); agent_enabled=[bool]$EnableAgent } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $local 'run.json') -Encoding utf8
for ($i=0; $i -lt 40; $i++) {
    if ($process.HasExited) { throw "Java exited. Inspect $local\stdout.log and stderr.log (no credentials are printed by this launcher)." }
    try {
        $health=Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2
        if ($health.status -eq 'ok') {
            Write-Output "Java business is ready: http://127.0.0.1:$Port/"
            Write-Output "PID: $($process.Id); Agent enabled: $([bool]$EnableAgent)"
            Write-Output "Credentials: $tokenFile ($credentialSource)"
            exit 0
        }
    } catch { Start-Sleep -Milliseconds 500 }
}
throw "Startup did not become ready; inspect $local\stdout.log and stderr.log. The process was not forcibly stopped."
