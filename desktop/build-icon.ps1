$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$assetDirectory = Join-Path $PSScriptRoot 'assets'
$sourcePath = Join-Path $assetDirectory 'team-logo.png'
$iconPath = Join-Path $assetDirectory 'team-logo-rounded.ico'
$image = [System.Drawing.Image]::FromFile($sourcePath)
$frames = @()
try {
    # Render the original logo inside a rounded application tile.
    foreach ($size in @(16, 24, 32, 48, 64, 128, 256)) {
        $renderSize = $size * 4
        $tile = New-Object System.Drawing.Bitmap $renderSize, $renderSize
        $tileGraphics = [System.Drawing.Graphics]::FromImage($tile)
        $outline = New-Object System.Drawing.Drawing2D.GraphicsPath
        $bitmap = New-Object System.Drawing.Bitmap $size, $size
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $stream = New-Object System.IO.MemoryStream
        try {
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.Clear([System.Drawing.Color]::Transparent)
            $tileGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $tileGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $tileGraphics.Clear([System.Drawing.Color]::Transparent)
            $diameter = [single]($renderSize * 0.46)
            $edge = [single]$renderSize
            $outline.AddArc([single]0, [single]0, $diameter, $diameter, [single]180, [single]90)
            $outline.AddArc(($edge - $diameter), [single]0, $diameter, $diameter, [single]270, [single]90)
            $outline.AddArc(($edge - $diameter), ($edge - $diameter), $diameter, $diameter, [single]0, [single]90)
            $outline.AddArc([single]0, ($edge - $diameter), $diameter, $diameter, [single]90, [single]90)
            $outline.CloseFigure()
            $tileGraphics.SetClip($outline)
            $scale = [Math]::Min($renderSize / $image.Width, $renderSize / $image.Height)
            $width = [int][Math]::Round($image.Width * $scale)
            $height = [int][Math]::Round($image.Height * $scale)
            $rectangle = New-Object System.Drawing.Rectangle ([int](($renderSize - $width) / 2)), ([int](($renderSize - $height) / 2)), $width, $height
            $tileGraphics.DrawImage($image, $rectangle)
            $graphics.DrawImage($tile, 0, 0, $size, $size)
            $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
            $frames += @{ Size = $size; Bytes = $stream.ToArray() }
        } finally {
            $stream.Dispose()
            $graphics.Dispose()
            $bitmap.Dispose()
            $outline.Dispose()
            $tileGraphics.Dispose()
            $tile.Dispose()
        }
    }
} finally { $image.Dispose() }
$output = [System.IO.File]::Create($iconPath)
$writer = New-Object System.IO.BinaryWriter $output
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$frames.Count)
    $offset = 6 + 16 * $frames.Count
    foreach ($frame in $frames) {
        $dimension = if ($frame.Size -eq 256) { 0 } else { $frame.Size }
        $writer.Write([byte]$dimension)
        $writer.Write([byte]$dimension)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$frame.Bytes.Length)
        $writer.Write([uint32]$offset)
        $offset += $frame.Bytes.Length
    }
    foreach ($frame in $frames) { $writer.Write([byte[]]$frame.Bytes) }
} finally { $writer.Dispose() }
Write-Output "Application icon created: $iconPath"
