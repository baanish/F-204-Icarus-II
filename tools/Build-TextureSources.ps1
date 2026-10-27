# Builds the texture-sources ZIP: the generated images and arrays under art/textures/generated that only the skin
# rebuild reads. Git keeps their prompts and records; art/textures/texture-sources.json pins every file's SHA-256.
# Run it from a checkout that has the files (tools/Fetch-TextureSources.ps1 restores them). Entries are sorted and
# carry a fixed timestamp, so the same files always give the same ZIP bytes.
#
#   pwsh -NoProfile -File tools/Build-TextureSources.ps1                   # .cache/texture-sources/Icarus-v<version>-texture-sources.zip
#   pwsh -NoProfile -File tools/Build-TextureSources.ps1 -OutDirectory <dir>
#   pwsh -NoProfile -File tools/Build-TextureSources.ps1 -WriteManifest    # after adding, removing or recompressing sources
param(
    [string]$OutDirectory,
    [switch]$WriteManifest
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$sources = Join-Path $repo 'art/textures/generated'
$manifestPath = Join-Path $repo 'art/textures/texture-sources.json'
$fetch = 'pwsh -NoProfile -File tools/Fetch-TextureSources.ps1'
function Fail([string]$why) { Write-Output "TEXTURE SOURCES FAIL: $why"; exit 1 }
function Get-Sha256([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }

$record = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -AsHashtable
# Files the skin rebuild writes into art/textures/generated itself; they are outputs, never packed or pinned.
$outputs = @($record.outputs)
$onDisk = [Collections.Generic.SortedDictionary[string, string]]::new([StringComparer]::Ordinal)
foreach ($file in Get-ChildItem -LiteralPath $sources -Recurse -File -Include '*.png', '*.npz') {
    $path = [IO.Path]::GetRelativePath($repo, $file.FullName).Replace('\', '/')
    if ($path -cnotin $outputs) { $onDisk[$path] = $file.FullName }
}
if ($WriteManifest) {
    $files = [ordered]@{}
    foreach ($path in $onDisk.Keys) { $files[$path] = Get-Sha256 $onDisk[$path] }
    $json = [ordered]@{ outputs = $outputs; files = $files } | ConvertTo-Json -Depth 3
    [IO.File]::WriteAllText($manifestPath, $json.Replace("`r`n", "`n") + "`n", [Text.UTF8Encoding]::new($false))
    Write-Output "TEXTURE SOURCES MANIFEST: $($files.Count) files pinned in art/textures/texture-sources.json"
    exit 0
}

$manifest = $record.files
$missing = @($manifest.Keys | Where-Object { -not $onDisk.ContainsKey($_) })
if ($missing.Count) { Fail "$($missing.Count) pinned files are missing (first: $($missing[0])); fetch them with: $fetch" }
$extra = @($onDisk.Keys | Where-Object { -not $manifest.ContainsKey($_) })
if ($extra.Count) { Fail "$($extra.Count) files are not pinned (first: $($extra[0])); run tools/Build-TextureSources.ps1 -WriteManifest" }
foreach ($path in $onDisk.Keys) {
    if ((Get-Sha256 $onDisk[$path]) -cne $manifest[$path]) { Fail "$path differs from art/textures/texture-sources.json" }
}
# The provenance records pin the same bytes; a pack must not drift from them.
& python (Join-Path $repo 'tools/Make-TextureRecordsPortable.py') --check
if ($LASTEXITCODE -ne 0) { Fail 'texture records pin other hashes than these files' }

$version = [regex]::Match((Get-Content -LiteralPath (Join-Path $repo 'src/Icarus/IcarusPlugin.cs') -Raw), 'const string Version = "([^"]+)"').Groups[1].Value
if ($version -notmatch '^\d+\.\d+\.\d+$') { Fail "unreadable plugin version '$version'" }
if (-not $OutDirectory) { $OutDirectory = Join-Path $repo '.cache/texture-sources' }
New-Item -ItemType Directory -Force -Path $OutDirectory | Out-Null
$zipPath = Join-Path ([IO.Path]::GetFullPath($OutDirectory)) "Icarus-v$version-texture-sources.zip"
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath }
$entries = [Collections.Generic.SortedDictionary[string, string]]::new($onDisk, [StringComparer]::Ordinal)
$entries['texture-sources.json'] = $manifestPath
$archive = [IO.Compression.ZipFile]::Open($zipPath, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($name in $entries.Keys) {
        $entry = $archive.CreateEntry($name, [IO.Compression.CompressionLevel]::Optimal)
        $entry.LastWriteTime = [DateTimeOffset]::new(2026, 1, 1, 0, 0, 0, [TimeSpan]::Zero)
        $source = [IO.File]::OpenRead($entries[$name])
        try {
            $target = $entry.Open()
            try { $source.CopyTo($target) } finally { $target.Dispose() }
        } finally { $source.Dispose() }
    }
} finally { $archive.Dispose() }
Write-Output "TEXTURE SOURCES PASS: $zipPath $($onDisk.Count) files, $((Get-Item -LiteralPath $zipPath).Length) bytes, sha256 $(Get-Sha256 $zipPath)"
