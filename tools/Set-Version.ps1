# Sets the Icarus version everywhere Package-Release checks it (src/Icarus/IcarusPlugin.cs, src/Icarus/Icarus.csproj,
# unity/Assets/Blueprinter/Mods/icarus/modinfo.json) and renames the bundle, icarus_<version>.nobp, in every tracked
# file that loads it by name (the test scenarios and tools). The CHANGELOG's first entry, the README's version line and
# the release docs' example tags are prose, so they stay hand-edited.
#
#   pwsh -NoProfile -File tools/Set-Version.ps1 -Version 0.2.0
param([Parameter(Mandatory)][string]$Version)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Fail([string]$why) { Write-Output "SET VERSION FAIL: $why"; exit 1 }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { Fail "expected a version like 0.2.0, got '$Version'" }

$plugin = Join-Path $repo 'src/Icarus/IcarusPlugin.cs'
$old = [regex]::Match([IO.File]::ReadAllText($plugin), 'const string Version = "([^"]+)"').Groups[1].Value
if (-not $old) { Fail 'no Version constant in src/Icarus/IcarusPlugin.cs' }
if ($old -eq $Version) { Fail "already $Version" }

# ReadAllText and WriteAllText keep each file's line endings; the encoding stays UTF-8 without a BOM.
$utf8 = [Text.UTF8Encoding]::new($false)
function Edit([string]$path, [string]$pattern, [string]$replacement) {
    $text = [IO.File]::ReadAllText($path)
    $new = [regex]::Replace($text, $pattern, $replacement)
    if ($new -eq $text) { Fail "nothing to change in $path" }
    [IO.File]::WriteAllText($path, $new, $utf8)
}

Edit $plugin ('const string Version = "' + [regex]::Escape($old) + '"') "const string Version = `"$Version`""
Edit (Join-Path $repo 'src/Icarus/Icarus.csproj') ('<Version>' + [regex]::Escape($old) + '</Version>') "<Version>$Version</Version>"
Edit (Join-Path $repo 'unity/Assets/Blueprinter/Mods/icarus/modinfo.json') ('"version": "' + [regex]::Escape($old) + '"') "`"version`": `"$Version`""

$bundle = "icarus_$old.nobp"
$users = @(git -C $repo grep -l --fixed-strings $bundle -- 'tests' 'tools')
foreach ($path in $users) { Edit (Join-Path $repo $path) ([regex]::Escape($bundle)) "icarus_$Version.nobp" }
Write-Output "SET VERSION: $old -> $Version in the plugin, project and modinfo, and the bundle name in $($users.Count) files"
