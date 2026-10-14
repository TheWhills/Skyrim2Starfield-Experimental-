# Walk a route from walk_route.py. Places the player on each leg, aims, holds W, then reads position.
# Does not toggle god mode, deploy, or close the game. input.ps1 refuses to type unless Starfield is foreground.
# usage: walk.ps1 -Route route.txt -Out results.csv   (Starfield focused, console closed, god mode already off)
param([string]$Route, [string]$Out, [double]$StartLift = 0.15)
$env:LEGACY = '1'
$i = (Join-Path $PSScriptRoot 'input.ps1')
"leg,start_x,start_y,start_z,target_x,target_y,target_z,end_x,end_y,end_z,name" | Set-Content $Out
$leg = 0
foreach ($line in Get-Content $Route) {
  $line = $line.Trim()
  if (-not $line -or $line.StartsWith('start_x')) { continue }
  $t = $line -split '\s+', 9
  if ($t.Count -lt 9) { continue }
  $leg += 1
  $z = '{0:F2}' -f ([double]$t[2] + $StartLift)
  $seq = "key:grave|wait:700|type:player.setpos x $($t[0])|key:enter|wait:200|type:player.setpos y $($t[1])|key:enter|wait:200|type:player.setpos z $z|key:enter|wait:200|type:player.setangle z $($t[6])|key:enter|wait:350|key:grave|wait:500|hold:w,$($t[7])|wait:400"
  powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq $seq | Out-Null
  if ($LASTEXITCODE -ne 0) { "guard stopped (focus lost)"; break }
  $r = powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'readpos.ps1')
  if ($r -eq 'fail' -or -not $r -or $r -eq 'fail guard') { $end = ',,' }
  else { $e = $r.Trim().Split(' '); $end = "$($e[0]),$($e[1]),$($e[2])" }
  "$leg,$($t[0]),$($t[1]),$($t[2]),$($t[3]),$($t[4]),$($t[5]),$end,$($t[8])" | Add-Content $Out
  "leg $leg -> $($t[8])"
}
$py = $(if ($env:FO4SF_PYTHON) { $env:FO4SF_PYTHON } else { 'python' })
& $py (Join-Path $PSScriptRoot 'walk_route.py') --score $Out
exit $LASTEXITCODE
