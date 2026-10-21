# Link-WorktreeAssets.ps1
#
# Lets B0 (tools/Build-Icarus.ps1) run in a git worktree. The game content B0 needs is gitignored, so a worktree lacks
# it: this links the worktree's unity/Assets/Blueprinter/_donotship, unity/Packages/nuclearoption and
# unity/Assets/Plugins/BepInEx to the main checkout's, as directory junctions, and puts copies of the game's two script
# assemblies in the worktree's unity/Library/ScriptAssemblies (see below). It deletes nothing: a path that is already
# the right junction is left alone, and any other existing path fails the run.
#
# -Unlink removes those junctions again, the links only, never what they point at. Run it before
# `git worktree remove`, which would otherwise walk into main's content through them.
#
#   pwsh -NoProfile -File tools/Link-WorktreeAssets.ps1             # from the worktree, once
#   pwsh -NoProfile -File tools/Link-WorktreeAssets.ps1 -Unlink     # before git worktree remove
#   pwsh -NoProfile -File tools/Link-WorktreeAssets.ps1 -Main <main checkout>

param(
    [string]$Main,
    [switch]$Unlink
)

$ErrorActionPreference = 'Stop'
$worktree = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
if (-not $Main) {
    # A worktree's common git directory is the main checkout's .git.
    $common = git -C $worktree rev-parse --path-format=absolute --git-common-dir
    if ($LASTEXITCODE -ne 0) { throw "not a git checkout: $worktree" }
    $Main = Split-Path -Parent $common
}
$Main = [IO.Path]::GetFullPath($Main).TrimEnd('\')
if ($Main -eq $worktree) { throw "$worktree is the main checkout; run this from a worktree" }

foreach ($relative in 'unity/Assets/Blueprinter/_donotship', 'unity/Packages/nuclearoption', 'unity/Assets/Plugins/BepInEx') {
    $source = [IO.Path]::GetFullPath((Join-Path $Main $relative)).TrimEnd('\')
    $link = [IO.Path]::GetFullPath((Join-Path $worktree $relative)).TrimEnd('\')
    $item = Get-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
    $linked = $item -and $item.LinkType -eq 'Junction' -and [IO.Path]::GetFullPath([string]$item.Target).TrimEnd('\') -eq $source
    if ($Unlink) {
        if (-not $item) { Write-Output "absent: $relative"; continue }
        if (-not $linked) { throw "$link is not a junction to $source; left as it is" }
        # Non-recursive: removes the reparse point and fails on a real directory with content.
        [IO.Directory]::Delete($link, $false)
        Write-Output "unlinked: $relative"
        continue
    }
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "the main checkout has no $relative ($source)" }
    if ($linked) { Write-Output "linked: $relative"; continue }
    if ($item) { throw "$link exists and is not a junction to $source; move it aside first" }
    New-Item -ItemType Directory -Force (Split-Path -Parent $link) | Out-Null
    New-Item -ItemType Junction -Path $link -Target $source | Out-Null
    Write-Output "linked: $relative -> $source"
}
if ($Unlink) { return }

# The game's components resolve only once its two script assemblies sit in Library/ScriptAssemblies, read-only.
# Blueprinter's GameAssemblySync copies them there from an editor delayCall, which a batch build never reaches, so a
# fresh worktree's Library would load every stock prefab with missing scripts. These are the worktree's own copies.
$scripts = Join-Path $worktree 'unity/Library/ScriptAssemblies'
New-Item -ItemType Directory -Force $scripts | Out-Null
foreach ($name in 'Assembly-CSharp.dll', 'Assembly-CSharp-firstpass.dll') {
    $source = Join-Path $worktree "unity/Packages/nuclearoption/$name"
    $target = Join-Path $scripts $name
    if ((Test-Path -LiteralPath $target) -and (Get-FileHash -LiteralPath $source).Hash -eq (Get-FileHash -LiteralPath $target).Hash) {
        Write-Output "in place: Library/ScriptAssemblies/$name"
        continue
    }
    if (Test-Path -LiteralPath $target) { Set-ItemProperty -LiteralPath $target -Name IsReadOnly -Value $false }
    Copy-Item -LiteralPath $source -Destination $target -Force
    Set-ItemProperty -LiteralPath $target -Name IsReadOnly -Value $true
    Write-Output "copied: Library/ScriptAssemblies/$name"
}
