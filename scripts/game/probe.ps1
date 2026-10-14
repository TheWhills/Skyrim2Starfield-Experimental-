# Collision mapper: for each probe point, teleport 1.5 m above it, wait, read the player's position by OCR.
# PASS = within 0.6 m of the floor height; LOWER = landed 0.6-3 m below (e.g. a lower floor next to stairs);
# FALL = dropped more than 3 m (no collision: falling into the void); HELD = stopped well above;
# MOVED = ended more than 1 m away in X/Y (pushed out or never reached the point), so the height says nothing.
# usage: probe.ps1 -Points pts.txt -Out results.csv   (Starfield focused, in the cell, console closed)
param([string]$Points, [string]$Out, [double]$Drop = 1.5, [int]$SettleMs = 1800)
$env:LEGACY = '1'
$i = (Join-Path $PSScriptRoot 'input.ps1')
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq 'key:grave|wait:900|type:tgm|key:enter|wait:500|key:grave|wait:700' | Out-Null
"x,y,floor_z,end_x,end_y,end_z,result,piece" | Set-Content $Out
foreach ($line in Get-Content $Points) {
  $p = $line.Split(' ', 4); $x = $p[0]; $y = $p[1]; $z = [double]$p[2]; $name = $p[3]
  $sz = '{0:F2}' -f ($z + $Drop)
  powershell -NoProfile -ExecutionPolicy Bypass -File $i -Seq "key:grave|wait:800|type:player.setpos x $x|key:enter|wait:250|type:player.setpos y $y|key:enter|wait:250|type:player.setpos z $sz|key:enter|wait:400|key:grave|wait:$SettleMs" | Out-Null
  if ($LASTEXITCODE -ne 0) { "guard stopped (focus lost)"; break }
  $r = powershell -NoProfile -ExecutionPolicy Bypass -File $PSScriptRoot\readpos.ps1
  if ($r -eq 'fail' -or -not $r) { $res = 'UNREAD'; $e = @('', '', '') }
  else { $e = $r.Split(' '); $dz = [double]$e[2] - $z
         $dxy = [math]::Sqrt([math]::Pow([double]$e[0] - [double]$x, 2) + [math]::Pow([double]$e[1] - [double]$y, 2))
         $res = if ($dxy -gt 1.0) { 'MOVED' } elseif ($dz -lt -3) { 'FALL' } elseif ($dz -lt -0.6) { 'LOWER' } elseif ($dz -gt 1.2) { 'HELD' } else { 'PASS' } }
  "$x,$y,$z,$($e[0]),$($e[1]),$($e[2]),$res,$name" | Add-Content $Out
  "{0,-7} floor {1,7:F2} end {2,7}  {3}" -f $res, $z, $e[2], $name
}
