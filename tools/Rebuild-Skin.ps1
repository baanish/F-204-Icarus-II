param(
    [switch]$Render,
    [switch]$BuildPlugin
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$reviewRoot = Join-Path $repoRoot '.cache/review/wave2/p9b-round2/full'
$steps = [System.Collections.Generic.List[object]]::new()

function Invoke-SkinStep([string]$Executable, [string[]]$Arguments) {
    Write-Host ($Executable + ' ' + ($Arguments -join ' '))
    & $Executable @Arguments
    $code = $LASTEXITCODE
    $steps.Add([pscustomobject]@{ executable = $Executable; arguments = $Arguments; exit_code = $code })
    if ($code -ne 0) { throw "Skin rebuild failed with exit code $code" }
}

Push-Location $repoRoot
try {
    foreach ($mode in @('prepare', 'audit')) {
        Invoke-SkinStep 'pwsh' @('-NoProfile', '-File', 'tools/Run-Blender.ps1', '--background', '--factory-startup',
            '--python-exit-code', '1', '--python', 'art/blender/bake_skin.py', '--', $mode)
    }
    Invoke-SkinStep 'pwsh' @('-NoProfile', '-File', 'tools/Run-Blender.ps1', '--background', '--factory-startup',
        '--python-exit-code', '1', '--python', 'art/blender/pilot2_skin.py', '--', 'structure')
    Invoke-SkinStep 'python' @('art/textures/pilot2_parts.py', 'guides')
    Invoke-SkinStep 'python' @('art/textures/full_skin_guides.py', 'inventory')
    Invoke-SkinStep 'python' @('art/textures/full_skin_guides.py', 'check')
    Invoke-SkinStep 'python' @('art/textures/full_skin_registration.py')
    Invoke-SkinStep 'python' @('art/textures/compose_skin.py', 'compose')
    Invoke-SkinStep 'python' @('art/textures/panel_checks.py')
    Invoke-SkinStep 'python' @('art/textures/decal_checks.py')

    $reviewTextures = Join-Path $reviewRoot 'art/export/textures'
    New-Item -ItemType Directory -Force $reviewTextures | Out-Null
    $maps = @(1..4 | ForEach-Object { "Icarus_livery_$_.png" })
    $maps += @('n', 'm', 'ao', 'dmg_b', 'dmg_n' | ForEach-Object { "Icarus_skin_$_.png" })
    $maps += 'Icarus_livery_4_m.png'
    foreach ($name in $maps) {
        Copy-Item -LiteralPath (Join-Path 'art/export/textures' $name) -Destination $reviewTextures
    }
    foreach ($name in @('composition.json', 'surface_fields.npz', 'generated_base_assembled.png', 'bare_metal_masks.npz')) {
        Copy-Item -LiteralPath (Join-Path '.cache/review/wave2/p9b/02' $name) -Destination $reviewRoot
    }
    Invoke-SkinStep 'python' @('tools/export_manifest.py', '--write')
    Invoke-SkinStep 'python' @('art/textures/compose_skin.py', 'measure')
    Invoke-SkinStep 'python' @('art/textures/full_skin_checks.py', 'measure')
    Invoke-SkinStep 'python' @('art/textures/bare_metal_checks.py', '--current-maps')
    if ($BuildPlugin) {
        Invoke-SkinStep 'dotnet' @('build', 'src/Icarus', '-c', 'Release', '-o', '.cache/build-staging/dotnet')
    }
    if ($Render) {
        Invoke-SkinStep 'pwsh' @('-NoProfile', '-File', 'tools/Run-Blender.ps1', '--background', '--factory-startup',
            '--python-exit-code', '1', '--python', 'art/blender/full_skin_review.py', '--', '--overview-only')
        Invoke-SkinStep 'python' @('art/textures/full_skin_checks.py', 'sheets', '--overview-only')
        Invoke-SkinStep 'pwsh' @('-NoProfile', '-File', 'tools/Run-Blender.ps1', '--background', '--factory-startup',
            '--python-exit-code', '1', '--python', 'art/blender/skin_closeups.py', '--',
            '--out', (Join-Path $repoRoot '.cache/review/share/texture_art'))
    }
    Write-Host 'SKIN REBUILD PASS: ten production maps, export manifest and measurement gate'
}
finally {
    if (Test-Path -LiteralPath $reviewRoot) {
        $steps | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reviewRoot 'rebuild-commands.json') -Encoding utf8
    }
    Pop-Location
}
