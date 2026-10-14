# Stop the local AI team's infrastructure gracefully.
#   default : the proxy rejects new jobs, waits up to 60 s for running ones, marks leftovers abandoned, exits.
#   -Emergency : additionally sets mode "stopped" first (every new or queued request is refused immediately).
# It never unloads the LM Studio model (that would cut an active request); unload it yourself with `lms unload --all`.
param([string]$Python = $(if ($env:FO4SF_PYTHON) { $env:FO4SF_PYTHON } else { 'python' }), [int]$Port = 1235, [switch]$Emergency)
$g = Join-Path $PSScriptRoot 'guardian\guardian.py'
if ($Emergency) { & $Python $g stop }
& $Python $g shutdown --port $Port
Start-Sleep 3
try { Invoke-RestMethod "http://127.0.0.1:$Port/guardian/status" -TimeoutSec 2 | Out-Null; "proxy still running (finishing a job?); run again or wait" }
catch { "proxy stopped" }
& $Python $g status | Select-String '"running"|"queued"'
