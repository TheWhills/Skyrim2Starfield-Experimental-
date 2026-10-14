# usage: input.ps1 -Proc Starfield -Seq "key:enter","wait:1500","type:help foo 4","key:enter"
param([string]$Proc = 'Starfield', [string]$Seq)
Add-Type @'
using System; using System.Runtime.InteropServices;
public class In {
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] public struct INPUT { [FieldOffset(0)] public uint type; [FieldOffset(8)] public KEYBDINPUT ki; }
  [DllImport("user32.dll")] public static extern uint SendInput(uint n, INPUT[] i, int size);
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint type);
  [DllImport("user32.dll")] public static extern short VkKeyScan(char c);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, uint d, IntPtr e);
  public static void Click(int x, int y) { SetCursorPos(x, y); System.Threading.Thread.Sleep(120); mouse_event(2,0,0,0,IntPtr.Zero); System.Threading.Thread.Sleep(90); mouse_event(4,0,0,0,IntPtr.Zero); }
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
  public static void Legacy(byte vk, byte scan, bool up, bool ext) { keybd_event(vk, scan, (up ? 2u : 0u) | (ext ? 1u : 0u), IntPtr.Zero); }
  public static void Key(ushort scan, bool up, bool ext) {
    INPUT[] a = new INPUT[1]; a[0].type = 1; a[0].ki.wScan = scan;
    a[0].ki.dwFlags = 8u | (up ? 2u : 0u) | (ext ? 1u : 0u);
    SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
  }
}
'@
$names = @{ enter=0x0D; esc=0x1B; space=0x20; grave=0xC0; tab=0x09; up=0x26; down=0x28; left=0x25; right=0x27; shift=0x10; back=0x08 }
function Tap([int]$vk, [bool]$shift = $false) {
  $scan = [In]::MapVirtualKey($vk, 0)
  $ext = $vk -in 0x26,0x28,0x25,0x27
  if ($shift) { if ($env:LEGACY -eq "1") { [In]::Legacy(0x10, [byte][In]::MapVirtualKey(0x10,0), $false, $false) } else { [In]::Key([In]::MapVirtualKey(0x10,0), $false, $false) }; Start-Sleep -Milliseconds 40 }
  if ($env:LEGACY -eq "1") { [In]::Legacy([byte]$vk, [byte]$scan, $false, $ext); Start-Sleep -Milliseconds 160; [In]::Legacy([byte]$vk, [byte]$scan, $true, $ext); Start-Sleep -Milliseconds 80 } else { [In]::Key($scan, $false, $ext); Start-Sleep -Milliseconds 160; [In]::Key($scan, $true, $ext); Start-Sleep -Milliseconds 80 }
  if ($shift) { if ($env:LEGACY -eq "1") { [In]::Legacy(0x10, [byte][In]::MapVirtualKey(0x10,0), $true, $false) } else { [In]::Key([In]::MapVirtualKey(0x10,0), $true, $false) }; Start-Sleep -Milliseconds 40 }
}
# FOREGROUND_GUARD: never type into another app. Abort unless the target process owns the foreground window.
Add-Type @"
using System; using System.Runtime.InteropServices;
public class FgCheck {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
}
"@
function Assert-Foreground($procName) {
  $h = [FgCheck]::GetForegroundWindow(); $fp = 0; [FgCheck]::GetWindowThreadProcessId($h, [ref]$fp) | Out-Null
  $name = (Get-Process -Id $fp -ErrorAction SilentlyContinue).ProcessName
  if ($name -ne $procName) { Write-Error "ABORT: foreground window belongs to '$name', not '$procName'. No input sent."; exit 2 }
}
$p = Get-Process $Proc -ErrorAction Stop | Select-Object -First 1
[In]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
[In]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 400
Assert-Foreground $Proc
$steps = $Seq.Split('|')
foreach ($s in $steps) {
  Assert-Foreground $Proc
  $k, $v = $s.Split(':', 2)
  switch ($k) {
    'click' { $xy = $v.Split(','); [In]::Click([int]$xy[0], [int]$xy[1]) }
    'hold' { $hk, $ms = $v.Split(','); $vk = $names[$hk.ToLower()]; if (-not $vk) { $vk = [In]::VkKeyScan($hk[0]) -band 0xFF }; $sc = [In]::MapVirtualKey($vk,0); [In]::Legacy([byte]$vk,[byte]$sc,$false,$false); Start-Sleep -Milliseconds ([int]$ms); [In]::Legacy([byte]$vk,[byte]$sc,$true,$false) }
    'move' { $xy = $v.Split(','); [In]::mouse_event(1, [int]$xy[0], [int]$xy[1], 0, [IntPtr]::Zero) }
    'wait' { Start-Sleep -Milliseconds ([int]$v) }
    'key'  { $vk = $names[$v.ToLower()]; if (-not $vk -and $v.Length -eq 1) { $vk = [In]::VkKeyScan($v[0]) -band 0xFF }; Tap $vk }
    'type' { foreach ($c in $v.ToCharArray()) { $r = [In]::VkKeyScan($c); Tap ($r -band 0xFF) ((($r -shr 8) -band 1) -eq 1) } }
  }
}
"sent $($steps.Count) steps"
