# Creates a draft first, verifies uploaded digests, then publishes a prerelease.
param(
    [Parameter(Mandatory)][string]$Directory,
    [Parameter(Mandatory)][string]$Tag,
    # Publishes on a still-private repository, for a release made ahead of going public; NOMM can't fetch it until then.
    [switch]$AllowPrivate
)

$ErrorActionPreference = 'Stop'
if ($Tag -notmatch '^v\d+\.\d+\.\d+$') { throw 'Expected release tag v<major>.<minor>.<patch>' }
$Directory = (Resolve-Path -LiteralPath $Directory).Path
$repository = 'baanish/F-204-Icarus-II'
# GitHub returns assets in case-insensitive name order; NOMNOM imports the first asset, so the NOMM archive
# uploads first and every other name sorts after it.
$assets = @("Icarus-$Tag-nomm.zip", "Icarus-$Tag-plugin-only.zip", "Icarus-$Tag-texture-sources.zip", 'RELEASE-NOTES.md', 'SHA256SUMS.txt')
foreach ($name in $assets) {
    if (-not (Test-Path -LiteralPath (Join-Path $Directory $name) -PathType Leaf)) { throw "Missing release asset: $name" }
}
& pwsh -NoProfile -File (Join-Path $PSScriptRoot 'Verify-Release.ps1') -Directory $Directory -Tag $Tag
if ($LASTEXITCODE -ne 0) { throw 'Local release verification failed' }
$meta = Get-Content -LiteralPath (Join-Path $Directory 'meta.json') -Raw | ConvertFrom-Json

function Invoke-Gh {
    $result = & gh @args
    if ($LASTEXITCODE -ne 0) { throw "gh $($args[0]) failed (exit $LASTEXITCODE); any draft remains unpublished" }
    $result
}

# The existing tag must identify the packaged source. Annotated tags need dereferencing.
$repoInfo = (Invoke-Gh api "repos/$repository") -join "`n" | ConvertFrom-Json
if ($repoInfo.private -and -not $AllowPrivate) { throw 'The release repository must be public (pass -AllowPrivate to release ahead of going public)' }
$ref = (Invoke-Gh api "repos/$repository/git/ref/tags/$Tag") -join "`n" | ConvertFrom-Json
$target = $ref.object
while ($target.type -ceq 'tag') { $target = ((Invoke-Gh api "repos/$repository/git/tags/$($target.sha)") -join "`n" | ConvertFrom-Json).object }
if ($target.type -cne 'commit' -or $target.sha -cne $meta.sourceCommit) { throw 'Remote tag does not match the packaged source commit' }
$null = Invoke-Gh release create $Tag --repo $repository --verify-tag --draft --prerelease --title "F-204 Icarus II $Tag" --notes-file (Join-Path $Directory 'RELEASE-NOTES.md')
foreach ($name in $assets) { $null = Invoke-Gh release upload $Tag (Join-Path $Directory $name) --repo $repository }
# The releases/tags endpoint does not return drafts, so find the draft in the release list.
$release = @((Invoke-Gh api "repos/$repository/releases") -join "`n" | ConvertFrom-Json) | Where-Object { $_.tag_name -ceq $Tag -and $_.draft } | Select-Object -First 1
if (-not $release -or -not $release.prerelease -or @($release.assets).Count -ne $assets.Count -or
    (@($release.assets.name) -join "`n") -cne ($assets -join "`n")) { throw 'Draft asset order or prerelease metadata mismatch; draft remains unpublished' }
foreach ($name in $assets) {
    $uploaded = @($release.assets | Where-Object { $_.name -ceq $name })
    $path = Join-Path $Directory $name
    $digest = 'sha256:' + (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($uploaded.Count -ne 1 -or $uploaded[0].size -ne (Get-Item -LiteralPath $path).Length -or $uploaded[0].digest -cne $digest) {
        throw "Draft upload mismatch: $name; draft remains unpublished"
    }
}
$null = Invoke-Gh release edit $Tag --repo $repository --draft=false --prerelease
$jsonPath = Join-Path $Directory '.published-release.json'
try {
    (Invoke-Gh api "repos/$repository/releases/tags/$Tag") | Set-Content -LiteralPath $jsonPath -Encoding utf8NoBOM
    & pwsh -NoProfile -File (Join-Path $PSScriptRoot 'Verify-Release.ps1') -Directory $Directory -Tag $Tag -ReleaseJson $jsonPath
    if ($LASTEXITCODE -ne 0) { throw 'Published release verification failed' }
    $repoInfo = (Invoke-Gh api "repos/$repository") -join "`n" | ConvertFrom-Json
    if ($repoInfo.private -and -not $AllowPrivate) { throw 'Published release repository is private' }
    $download = Join-Path $Directory ('.download-check-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $download | Out-Null
    try {
        $null = Invoke-Gh release download $Tag --repo $repository --pattern $assets[0] --dir $download
        if ((Get-FileHash -LiteralPath (Join-Path $download $assets[0])).Hash -cne
            (Get-FileHash -LiteralPath (Join-Path $Directory $assets[0])).Hash) { throw 'Downloaded NOMM archive differs from local release' }
    } finally {
        # Delete only this run's download, then its empty directory.
        Remove-Item -LiteralPath (Join-Path $download $assets[0]) -ErrorAction SilentlyContinue
        [IO.Directory]::Delete($download, $false)
    }
} finally { Remove-Item -LiteralPath $jsonPath -ErrorAction SilentlyContinue }
Write-Output "PUBLISH PASS: https://github.com/$repository/releases/tag/$Tag"
