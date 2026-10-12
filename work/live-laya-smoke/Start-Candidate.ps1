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
$expectedCommit = '187bf120df0820d6173cb88eee10c88fe63cfe75'

if (-not (Test-Path -LiteralPath $python)) {
    throw "The local Laya Python runtime is unavailable: $python"
}

$actualCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($actualCommit -ne $expectedCommit) {
    throw "Candidate source changed: expected $expectedCommit, got $actualCommit"
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$state = Join-Path $runtime 'candidate-state.json'
$log = Join-Path $runtime 'candidate-decisions.jsonl'
$status = Join-Path $runtime 'candidate-runtime-status.json'
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
    device = $Device
    interval_seconds = $Interval
} | ConvertTo-Json -Depth 3
