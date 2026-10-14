# Start the local AI team's infrastructure (interactive use; not a service or scheduled task).
#   1. checks LM Studio's server (:1234) and the loaded model
#   2. starts the Resource Guardian proxy (:1235) if it isn't running (single instance)
#   3. prints the team status
# Then run `opencode` in the repository (the Lead is the default agent).
param([string]$Python = $(if ($env:FO4SF_PYTHON) { $env:FO4SF_PYTHON } else { 'python' }), [int]$Port = 1235)
$here = $PSScriptRoot
$state = if ($env:FO4_AI_TEAM_STATE) { $env:FO4_AI_TEAM_STATE } else { Join-Path $env:LOCALAPPDATA 'fo4-ai-team\state' }   # outside the repo (guard.py scans the tree)
New-Item -ItemType Directory -Force $state | Out-Null
try { $s = Invoke-RestMethod "http://127.0.0.1:$Port/guardian/status" -TimeoutSec 2; "guardian proxy already running (mode $($s.mode))" }
catch {
  $p = Start-Process -FilePath $Python -ArgumentList (Join-Path $here 'guardian\proxy.py'), '--port', $Port `
       -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $state 'proxy.out.txt') `
       -RedirectStandardError (Join-Path $state 'proxy.err.txt')
  Start-Sleep 2
  if ($p.HasExited) { "guardian proxy failed to start; see $state\proxy.err.txt"; exit 1 }
  "guardian proxy started (pid $($p.Id), port $Port)"
}
try { $m = Invoke-RestMethod 'http://127.0.0.1:1234/api/v0/models' -TimeoutSec 3; $loaded = @($m.data | Where-Object state -eq 'loaded')
  if ($loaded.Count -eq 0) { "WARNING: no model loaded in LM Studio. Load the configured model, e.g. lms load <id> --context-length 16384" }
  else { "LM Studio model loaded: $($loaded.id -join ', ')" } }
catch { "WARNING: LM Studio server not reachable on :1234 (start it in LM Studio or with: lms server start)" }
& $Python (Join-Path $here 'guardian\guardian.py') status | Select-String '"level"|"mode"|"admission_if_new_job"'
