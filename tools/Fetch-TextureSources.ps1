# Restores the generated images and arrays the skin rebuild reads from the release's texture-sources ZIP, checking
# every file against art/textures/texture-sources.json. Building the mod (tools/Build-Icarus.ps1) does not need them.
#
#   pwsh -NoProfile -File tools/Fetch-TextureSources.ps1                  # gh release download of this version's ZIP
#   pwsh -NoProfile -File tools/Fetch-TextureSources.ps1 -Version 0.1.0
#   pwsh -NoProfile -File tools/Fetch-TextureSources.ps1 -Url <https URL of the ZIP>
#   pwsh -NoProfile -File tools/Fetch-TextureSources.ps1 -Zip <local ZIP>
#
# It never overwrites a source file that differs from its pinned hash; move such a file aside first.
param(
    [string]$Version,
    [string]$Url,
    [string]$Zip
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$repository = 'baanish/F-204-Icarus-II'
function Fail([string]$why) { Write-Output "TEXTURE SOURCES FAIL: $why"; exit 1 }
function Get-Sha256Bytes([byte[]]$bytes) { [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant() }

if (-not $Version) {
    $Version = [regex]::Match((Get-Content -LiteralPath (Join-Path $repo 'src/Icarus/IcarusPlugin.cs') -Raw), 'const string Version = "([^"]+)"').Groups[1].Value
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "expected a version like 0.1.0, got '$Version'" }
$name = "Icarus-v$Version-texture-sources.zip"
if (-not $Zip) {
    $download = Join-Path $repo '.cache/texture-sources'
    New-Item -ItemType Directory -Force -Path $download | Out-Null
    $Zip = Join-Path $download $name
    if ($Url) {
        if ($Url -notmatch '^https://') { Fail 'the -Url must be HTTPS' }
        Invoke-WebRequest -Uri $Url -OutFile $Zip
    } else {
        & gh release download "v$Version" --repo $repository --pattern $name --dir $download --clobber
        if ($LASTEXITCODE -ne 0) { Fail "gh could not download $name from release v$Version of $repository" }
    }
}
$Zip = (Resolve-Path -LiteralPath $Zip).Path

$manifest = (Get-Content -LiteralPath (Join-Path $repo 'art/textures/texture-sources.json') -Raw | ConvertFrom-Json -AsHashtable).files
$archive = [IO.Compression.ZipFile]::OpenRead($Zip)
try {
    $byName = @{}
    foreach ($entry in $archive.Entries) {
        if ($byName.ContainsKey($entry.FullName)) { Fail "duplicate entry $($entry.FullName)" }
        $byName[$entry.FullName] = $entry
    }
    foreach ($entryName in $byName.Keys) {
        if ($entryName -cne 'texture-sources.json' -and -not $manifest.ContainsKey($entryName)) { Fail "$name holds $entryName, which this checkout does not pin" }
    }
    $written = 0
    foreach ($path in $manifest.Keys) {
        if (-not $byName.ContainsKey($path)) { Fail "$name lacks $path; it was built for other sources than this checkout" }
        $stream = $byName[$path].Open()
        $buffer = [IO.MemoryStream]::new()
        try { $stream.CopyTo($buffer) } finally { $stream.Dispose() }
        $bytes = $buffer.ToArray()
        if ((Get-Sha256Bytes $bytes) -cne $manifest[$path]) { Fail "$path in $name differs from art/textures/texture-sources.json" }
        $target = Join-Path $repo $path
        if (Test-Path -LiteralPath $target) {
            if ((Get-Sha256Bytes ([IO.File]::ReadAllBytes($target))) -ceq $manifest[$path]) { continue }
            Fail "$path exists with other bytes; move it aside, then fetch again"
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        [IO.File]::WriteAllBytes($target, $bytes)
        $written++
    }
} finally { $archive.Dispose() }
Write-Output "TEXTURE SOURCES PASS: $($manifest.Count) files verified, $written written, from $name"
