# Builds build/icarus_livery_kit_<version>.zip, the paint reference pack for players' own liveries. See
# docs/livery-kit/README.md for what it holds. Needs the skin pipeline's outputs (tools/Rebuild-Skin.ps1; a cache hit
# restores the bake folder too) and the local asset export for the faction roundels.
# The Blender step (tools/livery_kit_model.py) is cached on its inputs in .cache/livery-kit/model-<key>, so a rebuild
# with an unchanged skin bake runs no Blender.
# Usage: pwsh -NoProfile -File tools/Build-LiveryKit.ps1 [-Bake <skin bake folder>]
param([string]$Bake)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function Fail([string]$why) { Write-Output "LIVERY KIT FAIL: $why"; exit 1 }
if (-not $Bake) { $Bake = Join-Path $repo '.cache/review/wave2/p9b/02' }
$Bake = [IO.Path]::GetFullPath($Bake)
$skin = Join-Path $Bake 'skin.blend'
if (-not (Test-Path -LiteralPath $skin -PathType Leaf)) { Fail "$skin is missing; run tools/Rebuild-Skin.ps1 first" }

$script = Join-Path $repo 'tools/livery_kit_model.py'
$key = (@($skin, $script, (Join-Path $repo 'art/blender/uvs.py'), (Join-Path $repo 'tools/scrub_fbx.py')) |
    ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash } | Join-String)
$key = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::ASCII.GetBytes($key))).Substring(0, 16).ToLowerInvariant()
$model = Join-Path $repo ".cache/livery-kit/model-$key"
if (-not (Test-Path -LiteralPath (Join-Path $model 'done'))) {
    $last = $null
    & pwsh -NoProfile -File (Join-Path $repo 'tools/Run-Blender.ps1') --background --factory-startup --python-exit-code 1 `
        --python $script -- $skin $model | ForEach-Object { $last = $_; if ("$_" -match 'LIVERY KIT MODEL|Error') { Write-Output "  $_" } }
    if ($LASTEXITCODE -ne 0) { Fail "the paint model step failed: $last" }
    New-Item -ItemType File -Path (Join-Path $model 'done') | Out-Null
} else { Write-Output "  paint model: cached $model" }
& python (Join-Path $repo 'tools/livery_kit.py') --model $model --bake $Bake
if ($LASTEXITCODE -ne 0) { exit 1 }
