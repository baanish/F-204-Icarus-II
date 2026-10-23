# Build-Icarus.ps1
#
# Builds the Icarus runtime DLL and the Blueprinter bundle. Passes only when the pinned exports match
# art/export-manifest.json, dotnet builds src/Icarus, Unity exits 0 with exactly one "[Icarus] Build complete: <nobp>"
# line, every authoring check A1 to A18 logged PASS, no "[Icarus] Captured build error" line, and the .nobp and DLL are
# newer than this run's start. Then copies them to build/ with SHA256SUMS.txt. Every Unity log stays in build/logs.
# The last line is always the verdict: "B0 PASS: ..." or "B0 FAIL: ...".
#
# Unity authors the aircraft first (IcarusAuthor.Author) from the export in art/export, which
# tools/export_blockout.py writes and tools/export_manifest.py --write pins.
#
#   pwsh -NoProfile -File tools/Build-Icarus.ps1
#   pwsh -NoProfile -File tools/Build-Icarus.ps1 -UnityPath <Unity.exe>

param(
    [string]$ExecuteMethod = 'Icarus.Editor.IcarusBuild.Build',
    [string]$UnityPath
)

$ErrorActionPreference = 'Stop'
# One build at a time machine-wide: the Unity project, the export folder and build/ are shared. A build that dies leaves
# the mutex abandoned, which the next one takes.
$buildLock = [System.Threading.Mutex]::new($false, 'Global\IcarusBuild')
try { [void]$buildLock.WaitOne() }
catch {
    $e = $_.Exception
    while ($e -and $e -isnot [System.Threading.AbandonedMutexException]) { $e = $e.InnerException }
    if (-not $e) { throw }
}
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$project = Join-Path $repo 'unity'
$build = Join-Path $repo 'build'
$logs = Join-Path $build 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$runStart = [DateTime]::UtcNow
$clock = [Diagnostics.Stopwatch]::StartNew()
$deadline = [TimeSpan]::FromMinutes(30)
$licenseFailure = 'No valid Unity Editor license found'
$maxLicenseRetries = 3
$checks = 1..18 | ForEach-Object { "A$_" }

function Fail([string]$why) {
    Write-Output "B0 FAIL: $why ($([int]$clock.Elapsed.TotalSeconds) s)"
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $repo 'art/export/blockout.json'))) {
    Fail 'no export in art/export; run tools/export_blockout.py in Blender'
}
& python (Join-Path $repo 'tools/export_manifest.py')
if ($LASTEXITCODE -ne 0) { Fail 'exports do not match art/export-manifest.json' }

# The plugin and the bundle ship as a pair, so they carry one version.
$csproj = Join-Path $repo 'src/Icarus/Icarus.csproj'
$dllVersion = ([xml](Get-Content -Raw -LiteralPath $csproj)).Project.PropertyGroup.Version | Where-Object { $_ } | Select-Object -First 1
$modVersion = (Get-Content -Raw -LiteralPath (Join-Path $project 'Assets/Blueprinter/Mods/icarus/modinfo.json') | ConvertFrom-Json).version
if ($dllVersion -ne $modVersion) { Fail "src/Icarus is version $dllVersion but modinfo.json is $modVersion" }

# Staged outside build/ until Unity succeeds, so a failed build never leaves a DLL beside an older bundle there.
$dotnetOut = Join-Path $repo '.cache/build-staging/dotnet'
# --no-incremental: an up-to-date skip would leave a DLL older than this run.
& dotnet build $csproj -c Release --no-incremental -o $dotnetOut --nologo | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "dotnet build exited $LASTEXITCODE" }
$dll = Join-Path $dotnetOut 'Icarus.dll'
if (-not (Test-Path -LiteralPath $dll) -or (Get-Item -LiteralPath $dll).LastWriteTimeUtc -lt $runStart) { Fail "dotnet build produced no fresh $dll" }
$plugins = Join-Path $project 'Assets/Plugins'
New-Item -ItemType Directory -Force $plugins | Out-Null
Copy-Item -LiteralPath $dll -Destination $plugins -Force
# The editor unloads Icarus.dll unless BepInEx and its own references resolve, and the project's imported game
# assemblies don't include them. Blueprinter never bundles a .dll.
$gameDir = if ($env:NUCLEAR_OPTION_DIR) { $env:NUCLEAR_OPTION_DIR } else { 'C:\Program Files (x86)\Steam\steamapps\common\Nuclear Option' }
$references = Join-Path $plugins 'BepInEx'
New-Item -ItemType Directory -Force $references | Out-Null
foreach ($name in 'BepInEx.dll', '0Harmony.dll', 'Mono.Cecil.dll', 'MonoMod.Utils.dll', 'MonoMod.RuntimeDetour.dll') {
    $source = Join-Path $gameDir "BepInEx/core/$name"
    $target = Join-Path $references $name
    if (-not (Test-Path -LiteralPath $target) -or (Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $target).Hash) {
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}
Write-Output 'dotnet: built and copied Icarus.dll to unity/Assets/Plugins'

$versionLine = Select-String -LiteralPath (Join-Path $project 'ProjectSettings/ProjectVersion.txt') -Pattern '^m_EditorVersion: (\S+)$'
$unityVersion = $versionLine.Matches[0].Groups[1].Value
if (-not $UnityPath) {
    $candidates = @(
        foreach ($root in 'HKLM:/SOFTWARE', 'HKLM:/SOFTWARE/WOW6432Node', 'HKCU:/SOFTWARE') {
            $icon = Get-ItemPropertyValue -LiteralPath "$root/Microsoft/Windows/CurrentVersion/Uninstall/Unity $unityVersion" -Name DisplayIcon -ErrorAction SilentlyContinue
            if ($icon) { ($icon -replace ',\s*-?\d+\s*$', '').Trim().Trim('"') }
        }
        Join-Path $env:ProgramFiles "Unity/Hub/Editor/$unityVersion/Editor/Unity.exe"
    )
    $UnityPath = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $UnityPath -or ((Get-Item -LiteralPath $UnityPath).VersionInfo.ProductVersion -split '_')[0] -ne $unityVersion) {
    Fail "Unity $unityVersion not found; pass -UnityPath"
}

# A crashed batch run leaves the lockfile behind; only a held lock means an editor has the project open.
$lock = Join-Path $project 'Temp/UnityLockfile'
if (Test-Path -LiteralPath $lock) {
    try { [IO.File]::Open($lock, 'Open', 'ReadWrite', 'None').Dispose() }
    catch [IO.IOException] { Fail 'an editor holds unity/Temp/UnityLockfile; close it first' }
}

for ($attempt = 1; ; $attempt++) {
    $log = Join-Path $logs ('unity-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + "-try$attempt.log")
    $arguments = @('-batchmode', '-quit', '-projectPath', "`"$project`"", '-executeMethod', $ExecuteMethod, '-logFile', "`"$log`"")
    $unityClock = [Diagnostics.Stopwatch]::StartNew()
    $unity = Start-Process -FilePath $UnityPath -ArgumentList $arguments -WindowStyle Hidden -PassThru
    $null = $unity.Handle  # cache the handle, or ExitCode reads back empty after exit
    Write-Output "unity: attempt $attempt, pid $($unity.Id), log $log"
    if (-not $unity.WaitForExit([int]$deadline.TotalMilliseconds)) {
        $unity.Kill()
        $unity.WaitForExit()
        Fail "Unity passed the $($deadline.TotalMinutes) minute deadline and was killed; log $log"
    }
    $exitCode = $unity.ExitCode
    Write-Output "unity: exit $exitCode after $([int]$unityClock.Elapsed.TotalSeconds) s"
    $licensed = -not (Select-String -LiteralPath $log -SimpleMatch $licenseFailure -Quiet)
    if ($exitCode -eq 0 -or $licensed -or $attempt -gt $maxLicenseRetries) { break }
    Write-Output "unity: license check failed, retrying in 30 s ($attempt of $maxLicenseRetries retries)"
    Start-Sleep -Seconds 30
}

$problems = @()
if ($exitCode -ne 0) { $problems += "Unity exited $exitCode" }
if (-not $licensed) { $problems += "license not found after $maxLicenseRetries retries" }
$markers = @(Select-String -LiteralPath $log -Pattern '^\[Icarus\] Build complete: (.+)$')
if ($markers.Count -ne 1) { $problems += "$($markers.Count) completion lines, expected 1" }
$captured = @(Select-String -LiteralPath $log -SimpleMatch '[Icarus] Captured build error')
if ($captured.Count -gt 0) { $problems += "$($captured.Count) captured build errors" }
$passed = @(Select-String -LiteralPath $log -Pattern '^\[Icarus\] check (A\d+) PASS' | ForEach-Object { $_.Matches[0].Groups[1].Value } | Sort-Object -Unique)
$missing = @($checks | Where-Object { $_ -notin $passed })
if ($missing.Count -gt 0) { $problems += "authoring checks without a PASS: $($missing -join ', ')" }
# Logged at editor startup, before the build method's capture exists; a prefab bound to an unloaded assembly's scripts
# would ship with missing components.
$unloaded = @(Select-String -LiteralPath $log -Pattern "^Assembly '(.+)' will not be loaded due to errors", '^Unloading broken assembly (\S+)')
if ($unloaded.Count -gt 0) { $problems += 'Unity did not load ' + (($unloaded | ForEach-Object { $_.Matches[0].Groups[1].Value } | Sort-Object -Unique) -join ', ') }
$nobp = if ($markers.Count -eq 1) { $markers[0].Matches[0].Groups[1].Value.Trim() }
if ($nobp -and -not (Test-Path -LiteralPath $nobp)) { $problems += "no .nobp at $nobp" }
elseif ($nobp -and (Get-Item -LiteralPath $nobp).LastWriteTimeUtc -lt $runStart) { $problems += "stale .nobp, last written $((Get-Item -LiteralPath $nobp).LastWriteTime) before this run" }
if ($problems) {
    Select-String -LiteralPath $log -Pattern 'error CS\d+|Captured build error|check A\d+ FAIL|executeMethod (class|method)|Exception:|will not be loaded|Unable to resolve reference|broken assembly' |
        Select-Object -First 8 | ForEach-Object { Write-Output "  log: $($_.Line.Trim())" }
    Fail (($problems -join '; ') + "; log $log")
}

$outputs = @($nobp, $dll)
$sums = foreach ($file in $outputs) {
    Copy-Item -LiteralPath $file -Destination $build -Force
    $name = Split-Path -Leaf $file
    (Get-FileHash -LiteralPath (Join-Path $build $name) -Algorithm SHA256).Hash.ToLowerInvariant() + '  ' + $name
}
[IO.File]::WriteAllLines((Join-Path $build 'SHA256SUMS.txt'), [string[]]$sums)
Write-Output "B0 PASS: build/$(Split-Path -Leaf $nobp) $($sums[0].Substring(0, 12)) with Icarus.dll $($sums[1].Substring(0, 12)), checks $($passed -join ' '), $attempt Unity attempt(s) ($([int]$clock.Elapsed.TotalSeconds) s)"
