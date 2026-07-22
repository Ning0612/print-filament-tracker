$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$sourcePath = Join-Path $root 'web\static\img\filament-ledger-icon.png'
$targetPath = Join-Path $root 'web\static\img\filament-ledger-icon.ico'
$icnsPath = Join-Path $root 'web\static\img\filament-ledger-icon.icns'
# Keep the checked-in ICO aligned with the Windows release build output.
$sizes = @(16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

$source = [Drawing.Image]::FromFile($sourcePath)
$payloads = foreach ($size in $sizes) {
    $bitmap = New-Object Drawing.Bitmap($size, $size, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([Drawing.Color]::Transparent)
    $graphics.CompositingMode = [Drawing.Drawing2D.CompositingMode]::SourceOver
    $graphics.CompositingQuality = [Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.DrawImage($source, 0, 0, $size, $size)

    $stream = New-Object IO.MemoryStream
    $bitmap.Save($stream, [Drawing.Imaging.ImageFormat]::Png)
    $bytes = $stream.ToArray()
    $stream.Dispose()
    $graphics.Dispose()
    $bitmap.Dispose()
    ,$bytes
}
$source.Dispose()

$file = New-Object IO.FileStream($targetPath, [IO.FileMode]::Create, [IO.FileAccess]::Write)
$writer = New-Object IO.BinaryWriter($file)
$writer.Write([UInt16]0)
$writer.Write([UInt16]1)
$writer.Write([UInt16]$sizes.Count)

$offset = 6 + (16 * $sizes.Count)
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $size = $sizes[$i]
    $bytes = $payloads[$i]
    $dimension = if ($size -eq 256) { 0 } else { $size }
    $writer.Write([Byte]$dimension)
    $writer.Write([Byte]$dimension)
    $writer.Write([Byte]0)
    $writer.Write([Byte]0)
    $writer.Write([UInt16]1)
    $writer.Write([UInt16]32)
    $writer.Write([UInt32]$bytes.Length)
    $writer.Write([UInt32]$offset)
    $offset += $bytes.Length
}

foreach ($bytes in $payloads) { $writer.Write($bytes) }
$writer.Flush()
$writer.Dispose()
$file.Dispose()

function Write-BigEndianUInt32($writer, [UInt32]$value) {
    $writer.Write([Byte](($value -shr 24) -band 0xff))
    $writer.Write([Byte](($value -shr 16) -band 0xff))
    $writer.Write([Byte](($value -shr 8) -band 0xff))
    $writer.Write([Byte]($value -band 0xff))
}

$icnsTypes = @('ic07', 'ic08', 'ic09', 'ic10')
$icnsSizes = @(128, 256, 512, 1024)
$icnsSource = [Drawing.Image]::FromFile($sourcePath)
$icnsPayloads = foreach ($size in $icnsSizes) {
    $bitmap = New-Object Drawing.Bitmap($size, $size, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([Drawing.Color]::Transparent)
    $graphics.CompositingQuality = [Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.DrawImage($icnsSource, 0, 0, $size, $size)
    $stream = New-Object IO.MemoryStream
    $bitmap.Save($stream, [Drawing.Imaging.ImageFormat]::Png)
    $bytes = $stream.ToArray()
    $stream.Dispose()
    $graphics.Dispose()
    $bitmap.Dispose()
    ,$bytes
}
$icnsSource.Dispose()

$icnsLength = 8
for ($i = 0; $i -lt $icnsPayloads.Count; $i++) { $icnsLength += 8 + $icnsPayloads[$i].Length }
$icnsFile = New-Object IO.FileStream($icnsPath, [IO.FileMode]::Create, [IO.FileAccess]::Write)
$icnsWriter = New-Object IO.BinaryWriter($icnsFile)
$icnsWriter.Write([Text.Encoding]::ASCII.GetBytes('icns'))
Write-BigEndianUInt32 $icnsWriter $icnsLength
for ($i = 0; $i -lt $icnsPayloads.Count; $i++) {
    $icnsWriter.Write([Text.Encoding]::ASCII.GetBytes($icnsTypes[$i]))
    Write-BigEndianUInt32 $icnsWriter (8 + $icnsPayloads[$i].Length)
    $icnsWriter.Write($icnsPayloads[$i])
}
$icnsWriter.Flush()
$icnsWriter.Dispose()
$icnsFile.Dispose()

Write-Output "Wrote $targetPath ($($sizes -join ', ') px)"
Write-Output "Wrote $icnsPath ($($icnsSizes -join ', ') px)"
