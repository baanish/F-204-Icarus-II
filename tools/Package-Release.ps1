# Builds and verifies a release without publishing. See docs/RELEASE.md.
param(
    [switch]$AllowDirty,
    [switch]$SkipBuild,
    [string]$NotesFile,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$modId = 'baanish.icarus'
$repository = 'baanish/F-204-Icarus-II'
function Fail([string]$why) { Write-Output "RELEASE FAIL: $why"; exit 1 }
function Get-Sha256([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Invoke-Git {
    $result = & git -C $repo @args
    if ($LASTEXITCODE -ne 0) { Fail "git $($args -join ' ') exited $LASTEXITCODE" }
    $result
}
if ($SkipBuild -and -not $AllowDirty) { Fail '-SkipBuild requires -AllowDirty; releases must build from the release commit' }

$status = @(Invoke-Git status --porcelain)
if ($status.Count -and -not $AllowDirty) { Fail 'the tree is dirty; commit the release source first (-AllowDirty is for local checks)' }
$commit = Invoke-Git rev-parse HEAD
$version = [regex]::Match((Get-Content -LiteralPath (Join-Path $repo 'src/Icarus/IcarusPlugin.cs') -Raw), 'const string Version = "([^"]+)"').Groups[1].Value
$projectVersion = ([xml](Get-Content -LiteralPath (Join-Path $repo 'src/Icarus/Icarus.csproj') -Raw)).Project.PropertyGroup.Version | Where-Object { $_ } | Select-Object -First 1
$bundleVersion = (Get-Content -LiteralPath (Join-Path $repo 'unity/Assets/Blueprinter/Mods/icarus/modinfo.json') -Raw | ConvertFrom-Json).version
$changelogTop = [regex]::Match((Get-Content -LiteralPath (Join-Path $repo 'CHANGELOG.md') -Raw), '(?m)^## ([^\r\n]+)').Groups[1].Value
$changelogVersion = [regex]::Match($changelogTop, '^(\d+\.\d+\.\d+)(?:\s|$)').Groups[1].Value
if ($version -notmatch '^\d+\.\d+\.\d+$' -or $version -ne $projectVersion -or $version -ne $bundleVersion -or $version -ne $changelogVersion) {
    Fail "versions disagree: plugin $version, project $projectVersion, modinfo $bundleVersion, changelog $changelogVersion"
}
$credits = @{
    'audio/CREDITS.md' = 'unity/Assets/Blueprinter/Mods/icarus/Audio/CREDITS.md'
    'fonts/OFL.txt' = 'art/textures/fonts/OFL.txt'
}
foreach ($path in @('README.md', 'LICENSE', 'tools/Verify-Release.ps1') + @($credits.Values)) {
    if (-not (Test-Path -LiteralPath (Join-Path $repo $path) -PathType Leaf)) { Fail "$path is missing" }
}
& python (Join-Path $repo 'tools/export_manifest.py')
if ($LASTEXITCODE -ne 0) { Fail 'exports do not match art/export-manifest.json' }
# The release also carries the texture-sources ZIP; a checkout without the sources gets them from the last release.
& python (Join-Path $repo 'art/textures/texture_sources.py')
if ($LASTEXITCODE -ne 0) { Fail 'texture sources are missing; fetch the last release''s with: pwsh -NoProfile -File tools/Fetch-TextureSources.ps1 -Version <its version>' }
if ($CheckOnly) { Write-Output "RELEASE CHECK PASS: $version at $commit; no build performed"; exit 0 }
& python -m unittest discover -s (Join-Path $repo 'tests') -p test_release_tools.py
if ($LASTEXITCODE -ne 0) { Fail 'release tool tests failed' }
$changes = if ($NotesFile) { Get-Content -LiteralPath $NotesFile -Raw } else { '' }

# Unity regenerates prefab fileIDs. Every other tracked source must survive the build.
# Hash text with normalized line endings so checkout CRLF conversion is not an asset change.
function Get-InputState {
    foreach ($path in @(Invoke-Git ls-files -- . ':(exclude,glob)unity/Assets/Blueprinter/Mods/icarus/**/*.prefab')) {
        $full = Join-Path $repo $path
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { "$path missing"; continue }
        $bytes = [IO.File]::ReadAllBytes($full)
        if ([Array]::IndexOf($bytes, [byte]0) -lt 0) {
            $bytes = [Text.Encoding]::UTF8.GetBytes([Text.Encoding]::UTF8.GetString($bytes).Replace("`r`n", "`n"))
        }
        "$path $([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)))"
    }
}
$nobpName = "icarus_$version.nobp"
$nobpPrefix = $null
if (-not $SkipBuild) {
    $before = @(Get-InputState) -join "`n"
    Write-Output "release: $modId $version from $commit; building"
    $buildLast = $null
    & pwsh -NoProfile -File (Join-Path $repo 'tools/Build-Icarus.ps1') | ForEach-Object { Write-Output "  $_"; $buildLast = $_ }
    if ($LASTEXITCODE -ne 0 -or $buildLast -notmatch '^B0 PASS: build/(\S+) ([0-9a-f]{12}) with Icarus\.dll') { Fail "the build did not pass: $buildLast" }
    $builtName = $Matches[1]
    $nobpPrefix = $Matches[2]
    if ($builtName -cne $nobpName) { Fail "the build wrote $builtName, expected $nobpName" }
    if ((@(Get-InputState) -join "`n") -cne $before) { Fail 'the build changed tracked inputs other than generated prefabs' }
    if (-not $AllowDirty -and @(Invoke-Git ls-files --others --exclude-standard).Count) { Fail 'the build created untracked inputs; review and commit them first' }
} else { Write-Output "release: reusing build/$nobpName and build/Icarus.dll for a local packaging check" }

# Match the build's machine-wide mutex while checking and copying its paired outputs.
$buildLock = [Threading.Mutex]::new($false, 'Global\IcarusBuild')
try { [void]$buildLock.WaitOne() }
catch {
    $e = $_.Exception
    while ($e -and $e -isnot [Threading.AbandonedMutexException]) { $e = $e.InnerException }
    if (-not $e) { throw }
}
try {
    $build = Join-Path $repo 'build'
    $sums = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $build 'SHA256SUMS.txt')) {
        if ($line -match '^([0-9a-f]{64})  (\S+)$') { $sums[$Matches[2]] = $Matches[1] }
    }
    if (-not $sums.ContainsKey($nobpName) -or ($nobpPrefix -and -not $sums[$nobpName].StartsWith($nobpPrefix))) { Fail 'another build replaced build/ after this one passed' }
    foreach ($name in $nobpName, 'Icarus.dll') {
        if (-not $sums.ContainsKey($name) -or (Get-Sha256 (Join-Path $build $name)) -cne $sums[$name]) { Fail "build/$name differs from build/SHA256SUMS.txt" }
    }
    $assembly = [Reflection.AssemblyName]::GetAssemblyName((Join-Path $build 'Icarus.dll'))
    if ($assembly.Name -cne 'Icarus' -or $assembly.Version.ToString(3) -ne $version) { Fail "build/Icarus.dll is $($assembly.FullName)" }
    $local = if ($AllowDirty) { '-LOCAL' } else { '' }
    $tag = "v$version$local"
    $out = Join-Path $repo ('.cache/release/' + $tag + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
    New-Item -ItemType Directory -Path $out | Out-Null
    $metaPath = Join-Path $out 'meta.json'
    [ordered]@{
        id = $modId; sourceCommit = $commit; local = [bool]$AllowDirty
        bundle = [ordered]@{ fileName = $nobpName; hash = "sha256:$($sums[$nobpName])" }
        artifact = [ordered]@{
            fileName = 'Icarus.dll'; version = $version; category = 'preRelease'; type = 'plugin'
            gameVersion = '0.34.2'; downloadUrl = ''; hash = "sha256:$(Get-Sha256 (Join-Path $build 'Icarus.dll'))"
            dependencies = @([ordered]@{ id = 'com.nikkorap.blueprinter'; version = '2.1.1' })
        }
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $metaPath -Encoding utf8NoBOM
    $sourceUrl = "https://github.com/$repository/blob/v$version"
    $readme = Get-Content -LiteralPath (Join-Path $repo 'README.md') -Raw
    $readme = [regex]::Replace($readme, '(?<lead>!?\[[^\]]*\]\()(?<path>[^)\s]+)(?<tail>\))', {
        param($match)
        $path = $match.Groups['path'].Value
        if ($path -match '^(?:[a-z][a-z0-9+.-]*:|/|#)') { return $match.Value }
        $match.Groups['lead'].Value + "$sourceUrl/" + ($path -replace '^\./', '') + $match.Groups['tail'].Value
    })
    $readmePath = Join-Path $out 'README.md'
    [IO.File]::WriteAllText($readmePath, $readme, [Text.UTF8Encoding]::new($false))
    $files = @{
        'Icarus.dll' = Join-Path $build 'Icarus.dll'
        $nobpName = Join-Path $build $nobpName
        'meta.json' = $metaPath
        'README.md' = $readmePath
        'LICENSE' = Join-Path $repo 'LICENSE'
    }
    foreach ($name in $credits.Keys) { $files[$name] = Join-Path $repo $credits[$name] }

    # Ported from Centurion: sorted entries and a fixed timestamp make identical inputs byte-identical.
    function Write-ReleaseArchive([string]$name, [string]$prefix) {
        $path = Join-Path $out $name
        $archive = [IO.Compression.ZipFile]::Open($path, [IO.Compression.ZipArchiveMode]::Create)
        try {
            $names = [string[]]@($files.Keys)
            [Array]::Sort($names, [StringComparer]::Ordinal)
            foreach ($file in $names) {
                $entry = $archive.CreateEntry($prefix + $file, [IO.Compression.CompressionLevel]::Optimal)
                $entry.LastWriteTime = [DateTimeOffset]::new(2026, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
                $source = [IO.File]::OpenRead($files[$file])
                try {
                    $target = $entry.Open()
                    try { $source.CopyTo($target) } finally { $target.Dispose() }
                } finally { $source.Dispose() }
            }
        } finally { $archive.Dispose() }
        $path
    }
    $zips = @(
        Write-ReleaseArchive "Icarus-$tag-nomm.zip" ''
        Write-ReleaseArchive "Icarus-$tag-plugin-only.zip" "BepInEx/plugins/$modId/"
    )
} finally { $buildLock.ReleaseMutex(); $buildLock.Dispose() }
$sourcesLast = $null
& pwsh -NoProfile -File (Join-Path $repo 'tools/Build-TextureSources.ps1') -OutDirectory $out | ForEach-Object { Write-Output "  $_"; $sourcesLast = $_ }
if ($LASTEXITCODE -ne 0) { Fail "the texture-sources ZIP did not build: $sourcesLast" }
$sourcesZip = Join-Path $out "Icarus-$tag-texture-sources.zip"
if ($tag -cne "v$version") { Move-Item -LiteralPath (Join-Path $out "Icarus-v$version-texture-sources.zip") -Destination $sourcesZip }

$releaseUrl = "https://github.com/$repository/releases/download/$tag"
$notes = @(
    "# F-204 Icarus II $tag", '',
    'For Nuclear Option 0.34.2. Requires BepInEx 5 and Blueprinter 2.1.1 or later. Blueprinter is a separate dependency and is not bundled.', '',
    'Two-PC multiplayer validation is pending. This is a prerelease.', ''
)
if ($changes) { $notes += @('## Changes', '', $changes.Trim(), '') }
else { $notes += @('## Changes', '', "See the [changelog]($sourceUrl/CHANGELOG.md).", '') }
$notes += @(
    '## Install', '',
    'NOMM supplies the install folder for the flat NOMM archive. Confirm BepInEx 5 and Blueprinter 2.1.1+ are installed and Blueprinter is enabled.', '',
    "For manual installation, extract [Icarus-$tag-plugin-only.zip]($releaseUrl/Icarus-$tag-plugin-only.zip) beside NuclearOption.exe. It includes BepInEx/plugins/baanish.icarus/.", '',
    "[Install instructions]($sourceUrl/README.md#install) | [Known issues]($sourceUrl/README.md#known-issues)", '',
    "[Icarus-$tag-texture-sources.zip]($releaseUrl/Icarus-$tag-texture-sources.zip) holds the generated texture source images for rebuilding the skin; installing and playing do not need it.", '',
    "Source commit: [$commit](https://github.com/$repository/commit/$commit).", '',
    "[SHA256SUMS.txt]($releaseUrl/SHA256SUMS.txt) covers the three archives and these notes."
)
if ($AllowDirty) { $notes = @('LOCAL REHEARSAL. NEVER PUBLISH. sourceCommit names the base commit; the payload includes uncommitted changes.', '') + $notes }
$notes | Set-Content -LiteralPath (Join-Path $out 'RELEASE-NOTES.md') -Encoding utf8NoBOM
$zips += $sourcesZip
$assets = @($zips) + (Join-Path $out 'RELEASE-NOTES.md')
[IO.File]::WriteAllLines((Join-Path $out 'SHA256SUMS.txt'), [string[]]@($assets | ForEach-Object { (Get-Sha256 $_) + '  ' + (Split-Path -Leaf $_) }))
$verifyArgs = @('-Directory', $out, '-Tag', "v$version")
if ($AllowDirty) { $verifyArgs += '-AllowLocal' }
& pwsh -NoProfile -File (Join-Path $repo 'tools/Verify-Release.ps1') @verifyArgs
if ($LASTEXITCODE -ne 0) { Fail 'the packaged release failed verification' }
Write-Output "package: $out"
foreach ($zip in $zips) { Write-Output "  $(Split-Path -Leaf $zip) $((Get-Item -LiteralPath $zip).Length) bytes sha256 $(Get-Sha256 $zip)" }
Write-Output "RELEASE $(if ($AllowDirty) { 'LOCAL (never publish)' } else { 'PASS' }): $out (HEAD $commit)"
