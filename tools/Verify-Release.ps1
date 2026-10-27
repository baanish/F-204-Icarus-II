# Offline archive checks; -ReleaseJson also checks saved GitHub release metadata.
param(
    [Parameter(Mandatory)][string]$Directory,
    [Parameter(Mandatory)][string]$Tag,
    [string]$ReleaseJson,
    [switch]$AllowLocal
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($Tag -notmatch '^v(\d+\.\d+\.\d+)$') { throw 'Expected release tag v<major>.<minor>.<patch>' }
if ($AllowLocal -and $ReleaseJson) { throw 'Local rehearsals cannot verify published releases' }
$version = $Matches[1]
$Directory = (Resolve-Path -LiteralPath $Directory).Path
$modId = 'baanish.icarus'
$repository = 'baanish/F-204-Icarus-II'
$suffix = if ($AllowLocal) { '-LOCAL' } else { '' }
$nommName = "Icarus-$Tag$suffix-nomm.zip"
$manualName = "Icarus-$Tag$suffix-plugin-only.zip"
$assetNames = @($nommName, $manualName, 'RELEASE-NOTES.md')
$releaseAssetNames = [string[]]($assetNames + 'SHA256SUMS.txt')
[Array]::Sort($releaseAssetNames, [StringComparer]::OrdinalIgnoreCase)
if ($releaseAssetNames[0] -cne $nommName) { throw 'Release asset names must sort with the NOMM archive first' }
function Get-Sha256([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }

$sums = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $Directory 'SHA256SUMS.txt')) {
    if ($line -cnotmatch '^([0-9a-f]{64})  ([A-Za-z0-9._-]+)$') { throw "Invalid checksum line: $line" }
    $name = $Matches[2]
    if ($name -cnotin $assetNames -or $sums.ContainsKey($name)) { throw "Unexpected or duplicate checksum: $name" }
    $sums[$name] = $Matches[1]
    if ((Get-Sha256 (Join-Path $Directory $name)) -cne $sums[$name]) { throw "Checksum mismatch: $name" }
}
if ($sums.Count -ne $assetNames.Count) { throw 'SHA256SUMS.txt must cover both archives and release notes' }
$payloadHashes = @{}
foreach ($name in @($nommName, $manualName)) {
    $archive = [IO.Compression.ZipFile]::OpenRead((Join-Path $Directory $name))
    try {
        $prefix = if ($name -ceq $manualName) { "BepInEx/plugins/$modId/" } else { '' }
        $required = @('Icarus.dll', "icarus_$version.nobp", 'meta.json', 'README.md', 'LICENSE', 'audio/CREDITS.md', 'fonts/OFL.txt')
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        $previous = ''
        foreach ($entry in $archive.Entries) {
            if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::Ordinal)) { throw "Unexpected path in ${name}: $($entry.FullName)" }
            $relative = $entry.FullName.Substring($prefix.Length)
            if ($relative -cnotin $required -or -not $seen.Add($relative)) { throw "Unexpected or duplicate entry in ${name}: $relative" }
            if ([StringComparer]::Ordinal.Compare($previous, $entry.FullName) -ge 0 -or
                $entry.LastWriteTime.DateTime -ne [DateTime]::new(2026, 1, 1)) { throw 'Archives require sorted entries and fixed timestamps' }
            $previous = $entry.FullName
            $stream = $entry.Open()
            try { $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream)).ToLowerInvariant() }
            finally { $stream.Dispose() }
            if ($name -ceq $nommName) { $payloadHashes[$relative] = $hash }
            elseif (-not $payloadHashes.ContainsKey($relative) -or $payloadHashes[$relative] -cne $hash) { throw "Archives disagree on $relative" }
        }
        foreach ($requiredName in $required) { if (-not $seen.Contains($requiredName)) { throw "$name is missing $requiredName" } }
        if ($name -ceq $nommName) {
            $reader = [IO.StreamReader]::new($archive.GetEntry('meta.json').Open())
            try { $metaText = $reader.ReadToEnd(); $meta = $metaText | ConvertFrom-Json } finally { $reader.Dispose() }
            if ($metaText -match '(?i)[a-z]:[\\/]|\\\\|"(?:path|enabled)"') { throw 'meta.json contains a local path or enabled state' }
            if ($meta.id -cne $modId -or $meta.sourceCommit -cnotmatch '^[0-9a-f]{40}$' -or $meta.local -isnot [bool] -or $meta.local -ne [bool]$AllowLocal -or
                $meta.artifact.fileName -cne 'Icarus.dll' -or $meta.artifact.version -cne $version -or $meta.artifact.downloadUrl -cne '' -or
                $meta.artifact.hash -cne "sha256:$($payloadHashes['Icarus.dll'])" -or $meta.artifact.type -cne 'plugin' -or
                $meta.artifact.category -cne 'preRelease' -or $meta.artifact.gameVersion -cne '0.34.2') { throw 'Packaged meta.json does not match the payload, commit or prerelease policy' }
            if ($meta.bundle.fileName -cne "icarus_$version.nobp" -or $meta.bundle.hash -cne "sha256:$($payloadHashes["icarus_$version.nobp"])") { throw 'Packaged bundle hash does not match the payload' }
            $dependencies = @($meta.artifact.dependencies)
            if ($dependencies.Count -ne 1 -or $dependencies[0].id -cne 'com.nikkorap.blueprinter' -or $dependencies[0].version -cne '2.1.1' -or
                $meta.artifact.PSObject.Properties['extends']) { throw 'Expected standalone plugin with Blueprinter dependency com.nikkorap.blueprinter, minimum 2.1.1' }
            if ((Get-Sha256 (Join-Path $Directory 'meta.json')) -cne $payloadHashes['meta.json']) { throw 'Staged meta.json differs from packaged metadata' }
        }
    } finally { $archive.Dispose() }
}
if ($ReleaseJson) {
    $release = Get-Content -LiteralPath $ReleaseJson -Raw | ConvertFrom-Json
    if ($release.tag_name -cne $Tag -or $release.draft -or -not $release.prerelease -or
        $release.html_url -cne "https://github.com/$repository/releases/tag/$Tag") { throw 'Expected a published prerelease at the requested tag' }
    $uploaded = @($release.assets)
    if ($uploaded.Count -ne $releaseAssetNames.Count -or (@($uploaded.name) -join "`n") -cne ($releaseAssetNames -join "`n")) {
        throw 'Upload exactly the checksummed assets and SHA256SUMS.txt in name order, with the NOMM archive first'
    }
    foreach ($asset in $uploaded) {
        $path = Join-Path $Directory $asset.name
        if ($asset.browser_download_url -cne "https://github.com/$repository/releases/download/$Tag/$($asset.name)" -or
            $asset.size -ne (Get-Item -LiteralPath $path).Length -or $asset.digest -cne "sha256:$(Get-Sha256 $path)") { throw "GitHub asset mismatch: $($asset.name)" }
    }
}
Write-Output "RELEASE VERIFY PASS: $Tag$suffix checksums, dependencies, commit, paired archives and sorted asset names"
