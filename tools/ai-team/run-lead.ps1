# Run the local Lead in cycles (interactive; not a Windows service or scheduled task). Stop with Ctrl+C,
# `guardian.py stop` (exits at the next check) or by deleting the pid file.
#   powershell -File tools\ai-team\run-lead.ps1 [-Interval 1800] [-MaxCycles 0] [-SessionTimeout 2700]
# Each cycle: skip if Starfield runs or the guardian is paused/stopped/blocked; make sure the guardian proxy and the
# model are up; run ONE Lead session in the Lead's own worktree (branch ai/local-lead, so its doc edits never collide
# with other agents in the main checkout); log it. Failures back off (x2, up to 4 h); success resets the interval.
param([int]$Interval = 1800, [int]$MaxCycles = 0, [int]$SessionTimeout = 2700,
      [string]$Python = $(if ($env:FO4SF_PYTHON) { $env:FO4SF_PYTHON } else { 'python' }))
$repo = Split-Path (Split-Path $PSScriptRoot)
$state = if ($env:FO4_AI_TEAM_STATE) { $env:FO4_AI_TEAM_STATE } else { Join-Path $env:LOCALAPPDATA 'fo4-ai-team\state' }
New-Item -ItemType Directory -Force $state | Out-Null
$log = Join-Path $state 'lead-cycles.log'
$pidFile = Join-Path $state 'run-lead.pid'
function Log($m) { $l = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss ') + $m; $l; Add-Content $log $l }

if (Test-Path $pidFile) {                                   # single instance
  $old = [int](Get-Content $pidFile)
  if (Get-Process -Id $old -ErrorAction SilentlyContinue) { "run-lead already running (pid $old)"; exit 1 }
}
$PID | Set-Content $pidFile

$wt = Join-Path (Split-Path $repo) 'fo4-to-starfield-wt\local-lead'
if (-not (Test-Path $wt)) {
  git -C $repo fetch -q origin main
  if (git -C $repo branch --list ai/local-lead) { git -C $repo worktree add $wt ai/local-lead | Out-Null }
  else { git -C $repo worktree add -b ai/local-lead $wt origin/main | Out-Null }
  Log "created Lead worktree $wt (branch ai/local-lead)"
}
$g = Join-Path $repo 'tools\ai-team\guardian\guardian.py'
# npm installs a .ps1 shim that Start-Process can't run: use the real binary behind it
$opencode = Join-Path (Split-Path (Get-Command opencode).Source) 'node_modules\opencode-ai\bin\opencode.exe'
$prompt = "Run ONE session of your operating procedure (your agent file + AGENTS.md). Do at most one task, then stop. " +
          "Good tasks for this team: QA review of open PRs labelled needs-qa (use fo4-qa; post the verdict with " +
          "gh pr review <n> --comment, prefixed 'QA (local):'); research questions from docs/ai/known-unknowns.md " +
          "(fo4-research, findings into docs/ai/research-log.md); refreshing docs/ai/agent-status.md from live sources. " +
          "At most one comment on #32, prefixed 'Lead (local):'. If nothing is ready, say so and stop."
$wait = $Interval; $cycle = 0
try {
  while ($MaxCycles -eq 0 -or $cycle -lt $MaxCycles) {
    $cycle++
    $st = & $Python $g status | ConvertFrom-Json
    if ($st.mode -eq 'stopped') { Log "guardian mode stopped: exiting"; break }
    $game = Get-Process Starfield, Fallout4 -ErrorAction SilentlyContinue
    if ($st.mode -eq 'paused' -or $game -or $st.level -eq 'block') {
      Log "cycle $cycle skipped: mode $($st.mode), level $($st.level), game $([bool]$game)"; Start-Sleep $Interval; continue
    }
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start-team.ps1') | Out-Null
    if (-not ((lms ps 2>&1 | Out-String) -match 'qwen3-14b')) {
      Log "model not loaded: loading"; & $Python (Join-Path $PSScriptRoot 'load_model.py') | Out-Null
    }
    git -C $wt pull -q --rebase --autostash origin main 2>$null
    Log "cycle ${cycle}: Lead session start (timeout $SessionTimeout s)"
    $out = Join-Path $state ("lead-session-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $p = Start-Process -FilePath $opencode -ArgumentList @('run', '--agent', 'fo4-lead', "`"$prompt`"") `
         -WorkingDirectory $wt -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError "$out.err"
    $null = $p.Handle                                   # hold the handle, or ExitCode is lost (redirected Start-Process)
    if (-not $p.WaitForExit($SessionTimeout * 1000)) {
      Stop-Process -Id $p.Id -Force -Confirm:$false; Log "cycle ${cycle}: session timed out, stopped"
      $wait = [Math]::Min($wait * 2, 14400)
    } elseif ($p.ExitCode -ne 0) {
      Log "cycle ${cycle}: session failed (exit $($p.ExitCode)), see $out"; $wait = [Math]::Min($wait * 2, 14400)
    } else {
      Log "cycle ${cycle}: session done, see $out"; $wait = $Interval
    }
    if ($MaxCycles -ne 0 -and $cycle -ge $MaxCycles) { break }
    Start-Sleep $wait
  }
} finally { Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue; Log "run-lead stopped" }
