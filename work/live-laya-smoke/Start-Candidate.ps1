param(
    [switch]$Start,
    [ValidateSet('auto', 'cpu', 'cuda')]
    [string]$Device = 'auto',
    [int]$Interval = 10
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = 'D:\steam\RimWorld Autopilot\.venv\Scripts\python.exe'
$runtime = Join-Path $PSScriptRoot 'runtime'

if (-not (Test-Path -LiteralPath $python)) {
    throw "The local Laya Python runtime is unavailable: $python"
}

$actualCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
$trackedChanges = @(& git -C $repoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect candidate source state at $repoRoot"
}
if ($trackedChanges.Count -gt 0) {
    throw "Candidate source has tracked changes; commit or revert them before launch"
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$state = Join-Path $runtime 'candidate-state.json'
$log = Join-Path $runtime 'candidate-decisions.jsonl'
# The MCP bridge recognizes only the installation-wide status location.  State,
# decision logs and PID remain isolated below $runtime; publishing this one
# status lets the bridge block manual MCP writes while the candidate is alive.
$status = 'D:\steam\RimWorld Autopilot\runtime-status.json'
$pidFile = Join-Path $runtime 'candidate.pid'
$stdout = Join-Path $runtime 'candidate.stdout.log'
$stderr = Join-Path $runtime 'candidate.stderr.log'

if (-not $Start) {
    [pscustomobject]@{
        candidate_commit = $actualCommit
        python = $python
        working_directory = $repoRoot
        state = $state
        log = $log
        status = $status
        pid = $pidFile
        stdout = $stdout
        stderr = $stderr
        source_clean = $true
        device = $Device
        interval_seconds = $Interval
    } | ConvertTo-Json -Depth 3
    exit 0
}

$arguments = @(
    '-u', '-B', 'colony_director.py',
    '--api-url', 'http://127.0.0.1:8765',
    '--device', $Device,
    '--interval', $Interval,
    '--state', $state,
    '--log', $log,
    '--pid-file', $pidFile,
    '--runtime-status', $status
)

$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
[pscustomobject]@{
    candidate_commit = $actualCommit
    pid = $process.Id
    state = $state
    log = $log
    status = $status
    stdout = $stdout
    stderr = $stderr
    source_clean = $true
    device = $Device
    interval_seconds = $Interval
} | ConvertTo-Json -Depth 3
