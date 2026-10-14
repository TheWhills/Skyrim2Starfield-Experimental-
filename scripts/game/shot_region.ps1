# Native-resolution capture of a screen region given as fractions of the screen (no downscaling, for OCR).
param([string]$Out, [double]$FX = 0.0, [double]$FY = 0.66, [double]$FW = 0.42, [double]$FH = 0.34)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public class Dpi2 { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
'@
[Dpi2]::SetProcessDPIAware() | Out-Null
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$x = [int]($b.Width * $FX); $y = [int]($b.Height * $FY); $w = [int]($b.Width * $FW); $h = [int]($b.Height * $FH)
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left + $x, $b.Top + $y, 0, 0, $bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
"saved $Out ${w}x${h} from screen $($b.Width)x$($b.Height)"
