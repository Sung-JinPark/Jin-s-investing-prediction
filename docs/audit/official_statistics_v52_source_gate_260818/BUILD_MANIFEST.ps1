$ErrorActionPreference = "Stop"

$reviewDirectory = (Resolve-Path $PSScriptRoot).Path
$repositoryRoot = (Resolve-Path (Join-Path $reviewDirectory "..\..\..")).Path
$reviewRelative = "docs/audit/official_statistics_v52_source_gate_260818"

$paths = [System.Collections.Generic.List[string]]::new()
$fixed = @(
    ".github/workflows/statistics-refresh.yml",
    ".gitignore",
    "README.md",
    "data/contracts/authoritative_statistics_sources.yaml",
    "data/contracts/website_data_lineage_v1.yaml",
    "data/statistics/dotcom_statistics_latest.json",
    "data/scenarios/candidates/scenario_v5_2_scenario_clustered_db_v4_latest.json",
    "docs/generated/inventory.generated.md",
    "src/ai_fc/authoritative_statistics.py",
    "src/ai_fc/cli.py",
    "src/ai_fc/official_data_workbook.py",
    "src/ai_fc/statistics_lab.py",
    "src/ai_fc/scenario_v5_2/artifact.py",
    "src/ai_fc/scenario_v5_2/audit.py",
    "src/ai_fc/scenario_v5_2/engine.py",
    "src/tests/test_authoritative_statistics.py",
    "src/tests/test_official_data_workbook.py",
    "src/tests/test_statistics_lab.py",
    "src/tests/test_scenario_v5_2.py",
    "src/tests/test_website_data_lineage.py",
    "$reviewRelative/PACKAGE_README_260818.md",
    "$reviewRelative/INDEPENDENT_REVIEW_260818.md",
    "$reviewRelative/SOURCE_AUTHORITY_MAPPING_260818.md",
    "$reviewRelative/V52_BEFORE_AFTER_260818.md",
    "$reviewRelative/TEST_AND_DEPLOY_EVIDENCE_260818.md",
    "$reviewRelative/LOCAL_BUILD_RENDER_EVIDENCE_260818.md",
    "$reviewRelative/DATA_INTEGRITY_SUMMARY_260818.json",
    "$reviewRelative/PROTECTED_HASH_COMPARISON_260818.json",
    "$reviewRelative/BUILD_MANIFEST.ps1"
)
foreach ($relative in $fixed) {
    $paths.Add($relative.Replace("\", "/"))
}

$dynamicRoots = @(
    "data/statistics/archive",
    "data/statistics/official_store",
    "data/statistics/workbooks",
    "outputs/official-data-ledger-260818",
    "_site",
    "$reviewRelative/screenshots"
)
foreach ($relativeRoot in $dynamicRoots) {
    $absoluteRoot = Join-Path $repositoryRoot $relativeRoot
    if (Test-Path -LiteralPath $absoluteRoot) {
        Get-ChildItem -LiteralPath $absoluteRoot -File -Recurse | ForEach-Object {
            $relative = $_.FullName.Substring($repositoryRoot.Length).TrimStart([char]'\', [char]'/')
            $paths.Add($relative.Replace("\", "/"))
        }
    }
}

$candidatePath = Join-Path $repositoryRoot "data/scenarios/candidates/scenario_v5_2_scenario_clustered_db_v4_latest.json"
$candidate = Get-Content -LiteralPath $candidatePath -Raw -Encoding UTF8 | ConvertFrom-Json
$protectedProperties = $candidate.build_receipt.protected_before.files.PSObject.Properties
foreach ($property in $protectedProperties) {
    $paths.Add(([string]$property.Name).Replace("\", "/"))
}

$uniquePaths = $paths | Sort-Object -Unique
$records = [System.Collections.Generic.List[object]]::new()
$shaLines = [System.Collections.Generic.List[string]]::new()
foreach ($relative in $uniquePaths) {
    $absolute = Join-Path $repositoryRoot $relative
    if (-not (Test-Path -LiteralPath $absolute -PathType Leaf)) {
        throw "Manifest input is missing: $relative"
    }
    $item = Get-Item -LiteralPath $absolute
    $sha = (Get-FileHash -LiteralPath $absolute -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaLines.Add("$sha  $relative")
    $records.Add([ordered]@{
        path = $relative
        sha256 = $sha
        bytes = $item.Length
    })
}

$shaPath = Join-Path $reviewDirectory "MANIFEST.sha256"
$jsonPath = Join-Path $reviewDirectory "MANIFEST.json"
[System.IO.File]::WriteAllLines($shaPath, $shaLines, [System.Text.UTF8Encoding]::new($false))
$manifest = [ordered]@{
    schema_version = 1
    algorithm = "sha256"
    generated_at = [DateTimeOffset]::UtcNow.ToString("o")
    git_head = (git -C $repositoryRoot rev-parse HEAD).Trim()
    branch = (git -C $repositoryRoot branch --show-current).Trim()
    file_count = $records.Count
    self_reference_excluded = @("$reviewRelative/MANIFEST.sha256", "$reviewRelative/MANIFEST.json")
    files = $records
}
[System.IO.File]::WriteAllText(
    $jsonPath,
    ($manifest | ConvertTo-Json -Depth 8),
    [System.Text.UTF8Encoding]::new($false)
)

Write-Output "Wrote $($records.Count) file hashes to $shaPath and $jsonPath"
