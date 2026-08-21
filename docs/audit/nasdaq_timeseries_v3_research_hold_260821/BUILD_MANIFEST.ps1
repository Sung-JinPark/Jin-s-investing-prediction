param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
)

$ErrorActionPreference = "Stop"
$reviewDirectory = $PSScriptRoot
function Get-RepositoryRelativePath([string]$Path) {
    $root = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd("\", "/")
    $full = [System.IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "path is outside repository root: $full"
    }
    return $full.Substring($root.Length + 1).Replace("\", "/")
}
$reviewRelative = Get-RepositoryRelativePath $reviewDirectory
$roots = @($reviewRelative)
$exclude = @(
    "$reviewRelative/MANIFEST.sha256",
    "$reviewRelative/MANIFEST.json",
    "$reviewRelative/NASDAQ_MULTIVARIATE_TIMESERIES_V3_RESEARCH_HOLD_260821.zip"
)
$files = foreach ($entry in $roots) {
    $path = Join-Path $RepositoryRoot $entry
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Get-Item -LiteralPath $path
    } elseif (Test-Path -LiteralPath $path -PathType Container) {
        Get-ChildItem -LiteralPath $path -File -Recurse
    }
}
$records = $files | Sort-Object FullName -Unique | ForEach-Object {
    $relative = Get-RepositoryRelativePath $_.FullName
    if ($exclude -notcontains $relative) {
        [pscustomobject]@{
            path = $relative
            bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
}
$shaLines = $records | ForEach-Object { "$($_.sha256)  $($_.path)" }
[System.IO.File]::WriteAllLines((Join-Path $reviewDirectory "MANIFEST.sha256"), $shaLines, [System.Text.UTF8Encoding]::new($false))
$payload = [ordered]@{
    schema_version = 1
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    file_count = @($records).Count
    self_reference_excluded = $exclude
    files = @($records)
}
[System.IO.File]::WriteAllText(
    (Join-Path $reviewDirectory "MANIFEST.json"),
    ($payload | ConvertTo-Json -Depth 6),
    [System.Text.UTF8Encoding]::new($false)
)
Write-Output "manifest files=$(@($records).Count)"
