# Phone notifications for every python run (ntfy topic skyrim-conversion-tj-92841). Loaded from the PowerShell
# profile (see docs/OWNER-SETUP.md): `python ...` runs as usual, then the phone gets "<script> <NPC/name>: done" or
# "... FAILED (exit N)" with the run time.
function notify($msg) {
    try { Invoke-RestMethod -Method Post -Uri "https://ntfy.sh/skyrim-conversion-tj-92841" -Body $msg | Out-Null } catch {}
}
function python {
    $t = Get-Date
    & python.exe @args
    $code = $LASTEXITCODE
    $script = ($args | Where-Object { "$_" -like "*.py" } | Select-Object -First 1)
    if (-not $script) { return }                       # interactive python / python -c: no notification
    $what = [System.IO.Path]::GetFileNameWithoutExtension("$script")
    $i = [array]::IndexOf($args, "--name"); if ($i -lt 0) { $i = [array]::IndexOf($args, "--npc") }
    if ($i -ge 0 -and $i + 1 -lt $args.Count) { $what += " " + $args[$i + 1] }
    $mins = [math]::Round(((Get-Date) - $t).TotalMinutes, 1)
    if ($code -eq 0) { notify "$what`: done ($mins min)" } else { notify "$what`: FAILED (exit $code, $mins min)" }
    $global:LASTEXITCODE = $code
}
