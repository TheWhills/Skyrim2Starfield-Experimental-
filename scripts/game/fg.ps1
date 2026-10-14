Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
public class Fg {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
'@
$h = [Fg]::GetForegroundWindow(); $sb = New-Object System.Text.StringBuilder 256; [Fg]::GetWindowText($h, $sb, 256) | Out-Null
$pid2 = 0; [Fg]::GetWindowThreadProcessId($h, [ref]$pid2) | Out-Null
$r = New-Object Fg+RECT; [Fg]::GetWindowRect($h, [ref]$r) | Out-Null
"foreground: '$($sb.ToString())' pid $pid2 ($((Get-Process -Id $pid2).ProcessName)) rect $($r.L),$($r.T) - $($r.R),$($r.B)"
$g = Get-Process Starfield; "starfield pid $($g.Id) handle $($g.MainWindowHandle)"
