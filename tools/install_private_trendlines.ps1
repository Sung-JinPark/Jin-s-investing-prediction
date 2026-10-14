<#
.SYNOPSIS
Install the private loopback updater with the user's existing Python runtime.
.DESCRIPTION
No elevation, package installation, credential access or public price upload.
Code is copied to a user-profile directory visible to Windows Task Scheduler,
independently of an ephemeral Git worktree and packaged-app AppData virtualization.
The private originals and revisions are preserved when upgrading or disabling.
#>
[CmdletBinding()]
param(
    [string]$RuntimeDirectory = (Join-Path $env:USERPROFILE '.jins-investing\trendlines'),
    [string]$PythonExecutable,
    [switch]$NoStart,
    [switch]$NoStartupRegistration,
    [switch]$SkipStartupRefresh,
    [switch]$Disable
)

$ErrorActionPreference = 'Stop'
$projectDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimePath = [IO.Path]::GetFullPath($RuntimeDirectory).TrimEnd('\', '/')
$appDirectory = Join-Path $runtimePath 'app'
$privateDirectory = Join-Path $appDirectory 'outputs\trendlines\private-research-view'
$launcherPath = Join-Path $appDirectory 'tools\run_private_trendlines.py'
$taskName = 'JinsInvesting-PrivateTrendlines'
$startupDirectory = [Environment]::GetFolderPath('Startup')
$startupPath = Join-Path $startupDirectory ($taskName + '.vbs')
$manifestPath = Join-Path $runtimePath 'installation.json'

function Assert-SafePath([string]$Path, [string]$Parent) {
    $absolute = [IO.Path]::GetFullPath($Path)
    $prefix = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/') + '\'
    if (-not $absolute.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Target is outside the intended runtime: $absolute"
    }
    $cursor = $absolute
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Runtime path must not contain a redirected directory: $cursor"
            }
        }
        $next = Split-Path -Parent $cursor
        if ($next -eq $cursor) { break }
        $cursor = $next
    }
    return $absolute
}

# Explicit test destinations are allowed, but never a drive root or the checkout.
if (-not (Split-Path -Leaf $runtimePath) -or $runtimePath -eq $projectDirectory -or
    $projectDirectory.StartsWith($runtimePath + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Choose a dedicated runtime directory, not a drive root or repository ancestor.'
}
$null = Assert-SafePath $appDirectory $runtimePath
New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null

if (-not $PythonExecutable) { $PythonExecutable = (Get-Command python.exe -ErrorAction Stop).Source }
$pythonPath = [IO.Path]::GetFullPath($PythonExecutable)
$pythonWindowless = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf) -or
    -not (Test-Path -LiteralPath $pythonWindowless -PathType Leaf)) {
    throw 'An existing Python installation with python.exe and pythonw.exe is required.'
}
$baseArguments = '-u "' + $launcherPath + '" --out "' + $privateDirectory + '"'
$arguments = $baseArguments
if ($SkipStartupRefresh) { $arguments += ' --no-startup-refresh' }

function Get-OwnedTask {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.Actions.Count -ne 1 -or $existing.Actions[0].Execute -ne $pythonWindowless -or
            $existing.Actions[0].Arguments -notin @($baseArguments, ($baseArguments + ' --no-startup-refresh'))) {
            throw 'A differently configured task already uses this name; it was left unchanged.'
        }
    }
    return $existing
}

function Stop-OwnedProcess {
    # Filter both executable and exact quoted launcher. Never stop other Python jobs.
    $needle = '"' + $launcherPath + '"'
    foreach ($process in (Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'")) {
        if ($process.ExecutablePath -eq $pythonWindowless -and $process.CommandLine -and
            $process.CommandLine.Contains($needle)) {
            Stop-Process -Id $process.ProcessId -ErrorAction Stop
        }
    }
}

if ($Disable) {
    $owned = Get-OwnedTask
    if ($owned) { Disable-ScheduledTask -InputObject $owned | Out-Null; Stop-ScheduledTask -InputObject $owned }
    if (Test-Path -LiteralPath $startupPath) {
        if (-not (Get-Content -LiteralPath $startupPath -Raw).Contains($launcherPath)) {
            throw 'The Startup file is not owned by this installation.'
        }
        Remove-Item -LiteralPath $startupPath
    }
    Stop-OwnedProcess
    Write-Output 'Private updater disabled; source and revision history preserved.'
    return
}

if (-not $NoStartupRegistration -or -not $NoStart) {
    $owned = Get-OwnedTask
    if ($owned) { Stop-ScheduledTask -InputObject $owned }
    Stop-OwnedProcess
}

function Copy-CodeFile([string]$Source, [string]$Relative) {
    $destination = Assert-SafePath (Join-Path $appDirectory $Relative) $runtimePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $Source -Destination $destination -Force
}

$sourcePackage = Join-Path $projectDirectory 'src\ai_fc'
foreach ($file in (Get-ChildItem -LiteralPath $sourcePackage -Recurse -File)) {
    if ($file.FullName -match '[\\/]__pycache__[\\/]' -or $file.Extension -eq '.pyc') { continue }
    $relative = $file.FullName.Substring($projectDirectory.Length + 1)
    Copy-CodeFile $file.FullName $relative
}
foreach ($relative in @('tools\run_private_trendlines.py', 'tools\refresh_private_trendlines.py',
    'tools\preview_trendlines.py', 'tools\install_private_trendlines.ps1')) {
    $source = Join-Path $projectDirectory $relative
    Copy-CodeFile $source $relative
}
# Read registered path constants without initializing a database.
$contractPaths = & $pythonPath -c "import sys,json;sys.path.insert(0,sys.argv[1]+'/src');from ai_fc.trendlines import contracts as c,critical as k;print(json.dumps([str(c.CONTRACT_RELATIVE),str(c.ASSET_REGISTRY_RELATIVE),str(c.SOURCE_POLICY_RELATIVE),str(k.POLICY_RELATIVE)]))" $projectDirectory
if ($LASTEXITCODE -ne 0) { throw 'Cannot locate the trendline contracts.' }
foreach ($relative in ($contractPaths | ConvertFrom-Json)) {
    Copy-CodeFile (Join-Path $projectDirectory $relative) $relative
}

# Validate imports using installed code and the existing dependencies, with no pip.
& $pythonPath $launcherPath --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Installed updater imports failed; startup was not registered.' }

# Seed only personal chart artifacts from this checkout. Existing immutable files
# must have identical bytes; existing mutable latest/export pointers are retained.
$seedDirectory = Join-Path $projectDirectory 'outputs\trendlines\private-research-view'
if (Test-Path -LiteralPath $seedDirectory -PathType Container) {
    $seedItems = @()
    $history = Join-Path $seedDirectory 'data\trendlines_research'
    if (Test-Path -LiteralPath $history) { $seedItems += Get-ChildItem -LiteralPath $history -Recurse -File }
    $seedItems += Get-ChildItem -LiteralPath $seedDirectory -File -Filter '*.trendlines.json'
    foreach ($file in $seedItems) {
        if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Seed evidence must be a regular file.' }
        $relative = $file.FullName.Substring($seedDirectory.Length + 1)
        $target = Assert-SafePath (Join-Path $privateDirectory $relative) $runtimePath
        $mutable = $relative -eq 'data\trendlines_research\latest.json' -or $relative.EndsWith('.trendlines.json')
        if (Test-Path -LiteralPath $target) {
            if (-not $mutable -and (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne
                (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash) {
                throw "Existing immutable evidence differs; left unchanged: $relative"
            }
            continue
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target
    }
}

$startupMethod = 'none'
if (-not $NoStartupRegistration) {
    try {
        # The program derives every path from its own absolute __file__. A
        # scheduler-provided working directory is unnecessary and some Windows
        # hosts reject a newly created AppData cwd with ERROR_DIRECTORY (267).
        $action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $arguments
        $triggers = @((New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)))
        foreach ($at in @('07:17', '09:17', '16:17')) { $triggers += New-ScheduledTaskTrigger -Daily -At $at }
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
            -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
            -Principal $principal -Description 'Private loopback trendlines; KST scheduling inside worker; no public prices.' -Force | Out-Null
        $startupMethod = 'scheduled_task'
        if (Test-Path -LiteralPath $startupPath) {
            if (-not (Get-Content -LiteralPath $startupPath -Raw).Contains($launcherPath)) { throw 'Startup file name collision.' }
            Remove-Item -LiteralPath $startupPath
        }
    } catch [Microsoft.Management.Infrastructure.CimException] {
        # Some Windows editions restrict task registration for a standard user.
        # A normal current-user Startup entry needs neither password nor elevation.
        if (Test-Path -LiteralPath $startupPath) {
            if (-not (Get-Content -LiteralPath $startupPath -Raw).Contains($launcherPath)) { throw 'Startup file name collision.' }
        }
        $command = '"' + $pythonWindowless + '" ' + $arguments
        $vbs = 'Set shell = CreateObject("WScript.Shell")' + "`r`n" +
            'shell.Run "' + $command.Replace('"', '""') + '", 0, False' + "`r`n"
        [IO.File]::WriteAllText($startupPath, $vbs, [Text.Encoding]::Unicode)
        $startupMethod = 'current_user_startup'
        Write-Warning 'Task registration was unavailable; current-user Startup was installed instead.'
    }
}

$manifest = [ordered]@{ schema_version = 1; runtime_directory = $runtimePath; app_directory = $appDirectory;
    python_executable = $pythonWindowless; launcher = $launcherPath; startup_method = $startupMethod;
    task_name = $taskName; installed_at = (Get-Date).ToString('o'); private_prices_only = $true;
    source_repository = $projectDirectory; refresh_times_kst = @('07:17', '09:17', '16:17') }
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding $false))
if (-not $NoStart) {
    if ($startupMethod -eq 'scheduled_task') { Start-ScheduledTask -TaskName $taskName }
    else { Start-Process -FilePath $pythonWindowless -ArgumentList $arguments -WorkingDirectory $appDirectory -WindowStyle Hidden }
}
$manifest | ConvertTo-Json -Depth 4
