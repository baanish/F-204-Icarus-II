# Checks staged blobs, working-tree files with -All, or commit text with -MessageFile.
[CmdletBinding(DefaultParameterSetName = 'Files')]
param(
    [string]$Repo = (Join-Path $PSScriptRoot '..'),
    [Parameter(ParameterSetName = 'Files')][switch]$All,
    [Parameter(Mandatory, ParameterSetName = 'Message')][string]$MessageFile
)

$ErrorActionPreference = 'Stop'
$Repo = [IO.Path]::GetFullPath($Repo)

function Read-GitBytes([string[]]$GitArgs) {
    $info = [Diagnostics.ProcessStartInfo]::new('git')
    $info.WorkingDirectory = $Repo
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($arg in $GitArgs) { $info.ArgumentList.Add($arg) }
    $process = [Diagnostics.Process]::Start($info)
    $errors = $process.StandardError.ReadToEndAsync()
    $output = [IO.MemoryStream]::new()
    try {
        $process.StandardOutput.BaseStream.CopyTo($output)
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) { throw "git failed: $($errors.GetAwaiter().GetResult().Trim())" }
        return ,$output.ToArray()
    } finally {
        $output.Dispose()
        $process.Dispose()
    }
}

function Read-GitPaths([string[]]$GitArgs) {
    $raw = [Text.Encoding]::UTF8.GetString((Read-GitBytes $GitArgs))
    return @($raw.Split([char]0, [StringSplitOptions]::RemoveEmptyEntries))
}

function Resolve-LfsBytes([byte[]]$Bytes, [string]$Path) {
    # A staged LFS pointer stands for the object git lfs stored at add time; inspect that object, not the pointer.
    $text = [Text.Encoding]::ASCII.GetString($Bytes, 0, [Math]::Min($Bytes.Length, 200))
    if (-not $text.StartsWith('version https://git-lfs.github.com/spec/v1')) { return ,$Bytes }
    if ($text -notmatch 'oid sha256:([0-9a-f]{64})') { throw "$Path has an unreadable LFS pointer" }
    $oid = $Matches[1]
    $common = [Text.Encoding]::UTF8.GetString((Read-GitBytes @('rev-parse', '--path-format=absolute', '--git-common-dir'))).Trim()
    $object = Join-Path $common "lfs/objects/$($oid.Substring(0, 2))/$($oid.Substring(2, 2))/$oid"
    if (-not (Test-Path -LiteralPath $object)) { throw "$Path has no local LFS object" }
    $real = [IO.File]::ReadAllBytes($object)
    if ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($real)).ToLowerInvariant() -cne $oid) {
        throw "$Path LFS object does not match its pointer"
    }
    return ,$real
}

function Read-TreeBytes([string]$Path) {
    if ($All) { return ,(Resolve-LfsBytes ([IO.File]::ReadAllBytes((Join-Path $Repo $Path))) $Path) }
    return ,(Resolve-LfsBytes (Read-GitBytes @('show', ":$Path")) $Path)
}

function Read-ScanBytes([byte[]]$Bytes, [string]$Path) {
    # Compressed PNG pixels can accidentally spell paths; retain every metadata chunk.
    if ($Path -notmatch '\.png$' -or $Bytes.Length -lt 8) { return ,$Bytes }
    $kept = [IO.MemoryStream]::new()
    try {
        $kept.Write($Bytes, 0, 8)
        $i = 8
        while ($i + 12 -le $Bytes.Length) {
            $length = ([long]$Bytes[$i] -shl 24) -bor ([long]$Bytes[$i + 1] -shl 16) -bor
                      ([long]$Bytes[$i + 2] -shl 8) -bor [long]$Bytes[$i + 3]
            if ($i + 12 + $length -gt $Bytes.Length) { throw "$Path has an invalid PNG chunk" }
            if ([Text.Encoding]::ASCII.GetString($Bytes, $i + 4, 4) -ne 'IDAT') {
                $kept.Write($Bytes, $i, [int]$length + 12)
            }
            $i += [int]$length + 12
        }
        if ($i -lt $Bytes.Length) { $kept.Write($Bytes, $i, $Bytes.Length - $i) }
        return ,$kept.ToArray()
    } finally { $kept.Dispose() }
}

function Test-PublicText([string]$Path, [string[]]$Views) {
    foreach ($rule in $rules.Keys) {
        # Binary bytes can match by chance, so this rule reads text only.
        if ($rule -eq 'private notes reference' -and ($Path -in @('.gitignore', 'tools/Check-Public.ps1') -or $Views[-2].Contains([char]0))) { continue }
        foreach ($view in $Views) {
            if ([regex]::IsMatch($view, $rules[$rule], 'IgnoreCase') -and "${Path}: $rule" -notin $failures) {
                $failures.Add("${Path}: $rule")
            }
        }
    }
}

try {
    if (-not $MessageFile -and (Read-GitBytes @('ls-files', '-u')).Length) { throw 'resolve unmerged index entries first' }
    $paths = if ($MessageFile) { @() }
             elseif ($All) { @(Read-GitPaths @('ls-files', '--cached', '--others', '--exclude-standard', '-z')) }
             else { @(Read-GitPaths @('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z')) }
    $rules = [ordered]@{
        'Steam ID' = '(?<!\d)7656119\d{10}(?!\d)'
        'absolute user path' = '(?:[A-Z]:[\\/]+Users[\\/]+|/(?:Users|home|root)/|\\\\[^\\\s]+\\(?:Users|home)\\)'
        'personal Steam library path' = '[A-Z]:[\\/]+(?:[^\s"<>|]*[\\/]+)?(?:Users[\\/]+[^\\/\s"<>|]+[\\/]+[^\r\n"<>|]*Steam|Steam(?:Library)?[\\/]+(?:users|userdata)[\\/]+[^\\/\s"<>|]+)'
    }
    # Names and patterns the owner keeps private: {"terms": [...], "patterns": {"rule name": "regex"}}.
    $termsPath = Join-Path $Repo 'tools/public-check-terms.json'
    # A linked worktree has no copy of the ignored file, so read the main checkout's.
    if (-not (Test-Path -LiteralPath $termsPath)) {
        $common = [Text.Encoding]::UTF8.GetString((Read-GitBytes @('rev-parse', '--path-format=absolute', '--git-common-dir'))).Trim()
        $termsPath = Join-Path (Split-Path $common -Parent) 'tools/public-check-terms.json'
    }
    if (Test-Path -LiteralPath $termsPath) {
        $config = Get-Content -LiteralPath $termsPath -Raw | ConvertFrom-Json -AsHashtable
        $terms = @($config.terms | Where-Object { $_ })
        if ($terms.Count) {
            $rules['private term'] = '(?<![A-Za-z0-9])(?:' + (($terms | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')(?![A-Za-z0-9])'
        }
        if ($config.patterns) {
            foreach ($name in $config.patterns.Keys) {
                if ($name -eq 'private notes reference' -and $All) { continue }
                $rules[$name] = $config.patterns[$name]
            }
        }
    } else { Write-Output 'PUBLIC NOTE: no tools/public-check-terms.json, so only the generic rules ran' }
    $failures = [Collections.Generic.List[string]]::new()
    if ($MessageFile) {
        $text = [IO.File]::ReadAllText($MessageFile)
        Test-PublicText 'commit message' @($text, $text.Replace([string][char]0, ''))
    }
    foreach ($path in $paths) {
        Write-Verbose "checking $path"
        if ($path -match '(?i)(^|/)(\.cache|_donotship)(/|$)|^unity/Packages/nuclearoption/|^unity/Assets/Blueprinter/(Example|Generated)/') {
            $failures.Add("${path}: local-only path")
        }
        if ($path -match '(?i)\.(dll|exe|nobp|unity3d|assets)(\.meta)?$') {
            $failures.Add("${path}: game or third-party binary")
        }
        $bytes = Read-TreeBytes $path
        $text = [Text.Encoding]::Latin1.GetString((Read-ScanBytes $bytes $path))
        $views = @($path, $text, $text.Replace([string][char]0, ''))
        Test-PublicText $path $views
        if ($path -match '(?i)\.fbx$') {
            $temp = [IO.Path]::GetTempFileName()
            try {
                [IO.File]::WriteAllBytes($temp, $bytes)
                $result = & python (Join-Path $PSScriptRoot 'scrub_fbx.py') $temp --check 2>&1
                if ($LASTEXITCODE -ne 0) { $failures.Add("${path}: invalid FBX or native/absolute metadata needs scrubbing") }
            } finally { Remove-Item -LiteralPath $temp -Force }
        }
    }

    $changed = if ($MessageFile) { @() } else { @(Read-GitPaths @('diff', '--cached', '--name-only', '-z')) }
    if (-not $MessageFile -and ($All -or @($changed | Where-Object { $_ -eq 'art/export-manifest.json' -or $_.StartsWith('art/export/') }).Count)) {
        $manifestBytes = Read-TreeBytes 'art/export-manifest.json'
        $manifest = [Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json -AsHashtable
        $exports = @(Read-GitPaths @('ls-files', '-z', '--', 'art/export/'))
        if (-not $exports.Count) { throw 'staged export manifest has no exports' }
        foreach ($path in @($exports + @($manifest.Keys) | Sort-Object -Unique)) {
            if ($path -notin $exports -or -not $manifest.ContainsKey($path)) {
                $failures.Add("${path}: missing or extra staged export")
                continue
            }
            $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData((Read-TreeBytes $path))).ToLowerInvariant()
            if ($digest -cne $manifest[$path]) { $failures.Add("${path}: staged export hash differs") }
        }
    }
    if ($failures.Count) {
        $failures | ForEach-Object { Write-Output "PUBLIC FAIL: $_" }
        exit 1
    }
    if ($MessageFile) { Write-Output 'PUBLIC PASS: commit message checked' }
    else {
        $mode = if ($All) { 'tracked and untracked working-tree' } else { 'staged' }
        Write-Output "PUBLIC PASS: $($paths.Count) $mode files checked"
    }
} catch {
    Write-Output "PUBLIC FAIL: $($_.Exception.Message)"
    exit 1
}
