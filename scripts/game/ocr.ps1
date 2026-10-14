# Read text from a screenshot region with the built-in Windows OCR engine (Windows.Media.Ocr).
# usage: ocr.ps1 -Image shot.png [-X 0 -Y 0 -W 0 -H 0]   (region in image pixels; 0 = whole image). Prints recognised lines.
param([string]$Image, [int]$X = 0, [int]$Y = 0, [int]$W = 0, [int]$H = 0, [int]$Scale = 2)
Add-Type -AssemblyName System.Drawing, System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait() | Out-Null; $task.Result }

# crop + upscale + invert-friendly copy (the console is light text on dark; OCR likes larger glyphs)
$src = [System.Drawing.Bitmap]::FromFile((Resolve-Path $Image))
if ($W -le 0) { $W = $src.Width - $X }; if ($H -le 0) { $H = $src.Height - $Y }
$dst = New-Object System.Drawing.Bitmap ($W * $Scale), ($H * $Scale)
$g = [System.Drawing.Graphics]::FromImage($dst); $g.InterpolationMode = 'HighQualityBicubic'
$g.DrawImage($src, (New-Object System.Drawing.Rectangle 0, 0, ($W * $Scale), ($H * $Scale)), (New-Object System.Drawing.Rectangle $X, $Y, $W, $H), 'Pixel')
$tmp = [IO.Path]::Combine([IO.Path]::GetTempPath(), "ocr_" + [guid]::NewGuid().ToString('N') + ".png")
$dst.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $dst.Dispose(); $src.Dispose()

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($tmp)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$stream.Dispose(); Remove-Item $tmp -ErrorAction SilentlyContinue
$result.Lines | ForEach-Object { $_.Text }
