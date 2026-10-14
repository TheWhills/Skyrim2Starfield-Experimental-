# Walk every route from routes.py in the game and record positions + a screenshot per route.
# usage: route_run.ps1 -Routes routes.json -Out <dir> [-First 0] [-Count 999]
# Requires: Starfield in front, in the route's cell, console CLOSED. Every keystroke goes through input.ps1's foreground
# guard (stops if anything else is in front). Results: <Out>\results.jsonl (one line per route), <Out>\r<k>.png.
param([string]$Routes, [string]$Out, [int]$First = 0, [int]$Count = 999, [int]$BackOff = 0, [string]$Only = '', [int]$StepIn = 0,[string]$PluginIndex = '02')
# -PluginIndex: FO4Port.esm's load-order prefix in the console (refs show as 02xxxxxx in this setup)
# -StepIn <ms>: walk towards a door before looking for the prompt (0 = press E from the route start, outside the swing arc)
# -BackOff <ms>: after E, walk backwards this long before crossing (gets out of the leaf's swing arc; one-sided blocks test)
# -Only 13,15: run just these route indices
$env:LEGACY = '1'
if (-not $env:FO4SF_PYTHON) { $env:FO4SF_PYTHON = 'C:\Modding\venv-render\Scripts\python.exe' }   # OCR prep needs numpy
$here = $PSScriptRoot
$i = Join-Path $here 'input.ps1'; $shot = Join-Path $here 'shot.ps1'; $readpos = Join-Path $here 'readpos.ps1'
New-Item -ItemType Directory -Force $Out | Out-Null
$res = Join-Path $Out 'results.jsonl'
$list = (Get-Content $Routes -Raw | ConvertFrom-Json).routes
$inv = [Globalization.CultureInfo]::InvariantCulture

function Read-Pos {
  # readpos leaves the console closed; if a read fails the console was probably open: close it once and retry
  $p = powershell -NoProfile -ExecutionPolicy Bypass -File $readpos
  # no blind console toggle on failure: readpos always leaves the console closed, and an extra toggle desynchronises
  # it (the next route's typing then goes to the game: "p" opens the Skills menu)
  if ($p -eq 'fail') { $p = powershell -NoProfile -ExecutionPolicy Bypass -File $readpos }
  # OCR sometimes drops or shifts a column (e.g. "91.43 0.52 91.43"): re-read up to twice when x equals z or a value is missing
  for ($n = 0; $n -lt 2; $n++) {
    $v = "$p".Trim().Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
    if ($v.Count -eq 3 -and $v[0] -ne $v[2]) { break }
    $p = powershell -NoProfile -ExecutionPolicy Bypass -File $readpos
  }
  return $p
}

$prevEnd = $null; $prevFar = $false
$onlySet = @($Only.Split(',', [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { [int]$_ })
for ($k = $First;$k -lt [Math]::Min($list.Count, $First + $Count); $k++) {
  if ($onlySet.Count -gt 0 -and $onlySet -notcontains $k) { continue }
  $r = $list[$k]
  $x, $y, $z = $r.start | ForEach-Object { $_.ToString($inv) }
  $h = $r.heading.ToString($inv)
  powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'console_open.ps1') | Out-Null
  if ($LASTEXITCODE -ne 0) { "console not confirmed open at route $k (code $LASTEXITCODE): stopping"; break }
  # both-side activation: an earlier route leaves the door open (then this side sees no OPEN prompt and only walks through
  # an open door). Close this route's door first by its Starfield ref id (plugin load index + local FormID from routes.py).
  $close = ''
  if ($r.use -and $r.sf_ref_local) { $close = "type:prid $PluginIndex$($r.sf_ref_local)|key:enter|wait:300|type:setopenstate 0|key:enter|wait:300|" }
  $seq = $close + "type:player.setpos x $x|key:enter|wait:350|type:player.setpos y $y|key:enter|wait:350|" +
         "type:player.setpos z $z|key:enter|wait:350|type:player.setangle z $h|key:enter|wait:350|" +
         "type:player.setangle x 10|key:enter|wait:400|key:grave|wait:1800"   # x 0 points the camera at the floor
  powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq $seq | Out-Null
  if ($LASTEXITCODE -ne 0) { "guard stopped at route $k"; break }
  # level the first-person camera: setangle x turns the actor, but the camera keeps its own mouse-look pitch (seen
  # stuck looking at the floor, so E never reached a door). Look fully up (clamps), then down a calibrated amount.
  powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq 'move:0,-2500|wait:250|move:0,-2500|wait:300|move:0,700|wait:500' | Out-Null
  $p0 = Read-Pos
  if ("$p0" -like 'fail console*') { "start read: $p0 at route ${k}: stopping"; break }
  # we just teleported there: a start read far from the target is an OCR misread (Parsons: "-0.00 6.40 0.00"), read again
  $v0 = "$p0".Trim().Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
  $far = $true
  try { $far = [Math]::Abs([double]$v0[0] - $r.start[0]) + [Math]::Abs([double]$v0[1] - $r.start[1]) -gt 3 } catch {}
  if ($v0.Count -ne 3 -or $far) {
    $p0 = Read-Pos
    $v0 = "$p0".Trim().Split(' ', [StringSplitOptions]::RemoveEmptyEntries)
    $far = $true
    try { $far = [Math]::Abs([double]$v0[0] - $r.start[0]) + [Math]::Abs([double]$v0[1] - $r.start[1]) -gt 3 } catch {}
    # still not where we teleported AND exactly where the last route ended: the teleport never ran, the console is out
    # of step (Parsons: a "p" opened the Skills menu and 12 routes read the same stale position). Stop instead of typing
    # into whatever menu is open. (Far but different is real: a start under the floor gets moved to a fallback spot.)
    # two invalid starts in a row both land on the entrance fallback, so only trust "same as last end" after a good route
    if ($far -and $prevEnd -and -not $prevFar -and "$p0".Trim() -eq "$prevEnd".Trim()) {
      "start read $p0 equals last end at route ${k}: console out of step, stopping"; break
    }
  }
  $prompt = $null; $verb = $null
  if ($far) {
    # the engine moved the player elsewhere (start under the floor -> cell entrance): nothing to test here, and pressing
    # E or walking from there hits whatever is in front (Parsons: E started a dialogue with the companion). Skip.
    $line = @{ index = $k; ref = $r.ref; kind = $r.kind; start_read = $p0; end_read = $p0; skipped = 'start not reached' } | ConvertTo-Json -Compress
    Add-Content $res $line
    "route $k $($r.kind) $($r.ref): start not reached ($p0), skipped"
    $prevEnd = $p0; $prevFar = $true
    continue
  }
  if ($r.use) {
    # step closer first: the activation prompt only appears within reach, and placements differ by ~1 m from the plane
    if ($StepIn -gt 0) { powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq "hold:w,$StepIn|wait:500" | Out-Null }
    # the levelled pitch is not reproducible between sessions (Parsons: aimed over the door, no prompt, E did nothing):
    # tilt down in small steps until the activation prompt is on screen. The last _pre shot is the evidence.
    $pre = Join-Path $Out "r${k}_pre.png"
    $prompt = $false
    for ($t = 0; $t -lt 9; $t++) {
      powershell -NoProfile -ExecutionPolicy Bypass -File $shot -Out $pre | Out-Null
      if ((& $env:FO4SF_PYTHON (Join-Path $here 'prompt_visible.py') $pre) -eq 'yes') { $prompt = $true; break }
      powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq 'move:0,150|wait:450' | Out-Null
    }
    # only open a closed door: a door left open by an earlier route shows CLOSE (or no prompt through the opening), and
    # E would shut it in the player's face. The verb is recorded with the result.
    $verb = ''
    if ($prompt) {
      # crop + threshold + enlarge first: the raw crop missed "OPEN" on bright backgrounds (37/37 read after prep)
      $vp = Join-Path $env:TEMP 'fo4sf_verb_prep.png'
      & $env:FO4SF_PYTHON (Join-Path $here 'prompt_verb_prep.py') $pre $vp
      $verb = ((powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'ocr.ps1') -Image $vp -Scale 1) -join ' ').Trim()
      # unreadable verb right after this route closed its own door (setopenstate 0): the door is closed, so open it,
      # but record it as unread rather than as a confirmed OPEN
      if ($verb -notmatch 'OPEN|CLOSE' -and $close) { $verb = 'unread-after-reset' }
    }
    if ($verb -match 'OPEN|unread-after-reset') { powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq 'key:e|wait:2200' | Out-Null }
    powershell -NoProfile -ExecutionPolicy Bypass -File $shot -Out (Join-Path $Out "r${k}_open.png") | Out-Null
    if ($BackOff -gt 0) { powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq "hold:s,$BackOff|wait:400" | Out-Null }
  }
  $walk = $r.walk_ms + $(if ($r.use) { $BackOff } else { 0 })   # walk back the distance we backed off
  powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq "hold:w,$walk|wait:700" | Out-Null
  if ($LASTEXITCODE -ne 0) { "guard stopped at route $k"; break }
  $p1 = Read-Pos
  if ("$p1" -like 'fail console*') { "end read: $p1 at route ${k}: stopping"; break }
  powershell -NoProfile -ExecutionPolicy Bypass -File $shot -Out (Join-Path $Out "r$k.png") | Out-Null
  $line = @{ index = $k; ref = $r.ref; kind = $r.kind; start_read = $p0; end_read = $p1; prompt = $prompt; verb = $verb } | ConvertTo-Json -Compress
  Add-Content $res $line
  $prevEnd = $p1; $prevFar = $far
  "route $k $($r.kind) $($r.ref): $p0 -> $p1"
}
