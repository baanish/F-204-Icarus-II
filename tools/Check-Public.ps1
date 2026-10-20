# Checks staged blobs, including binary metadata. Reports rules and paths without repeating leaked content.
param([string]$Repo = (Join-Path $PSScriptRoot '..'))

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

try {
    if ((Read-GitBytes @('ls-files', '-u')).Length) { throw 'resolve unmerged index entries first' }
    $paths = @(Read-GitPaths @('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'))
    $rules = [ordered]@{
        'private username' = [regex]::Escape(('own' + 'er'))
        'private email' = [regex]::Escape(('owner' + '@example.test'))
        'Steam ID' = '(?<!\d)7656119\d{10}(?!\d)'
        'absolute user path' = '(?:[A-Z]:[\\/]+Users[\\/]+|/(?:Users|home|root)/|\\\\[^\\\s]+\\(?:Users|home)\\)'
    }
    $failures = [Collections.Generic.List[string]]::new()
    foreach ($path in $paths) {
        if ($path -match '(?i)(^|/)(\.internal|\.cache|_donotship)(/|$)|^unity/Packages/nuclearoption/|^unity/Assets/Blueprinter/(Example|Generated)/') {
            $failures.Add("${path}: local-only path")
        }
        if ($path -match '(?i)\.(dll|exe|nobp|unity3d|assets)(\.meta)?$') {
            $failures.Add("${path}: game or third-party binary")
        }
        $bytes = Read-GitBytes @('show', ":$path")
        $text = [Text.Encoding]::Latin1.GetString((Read-ScanBytes $bytes $path))
        $views = @($path, $text, $text.Replace([string][char]0, ''))
        foreach ($rule in $rules.Keys) {
            if (@($views | Where-Object { $_ -imatch $rules[$rule] }).Count) {
                $failures.Add("${path}: $rule")
            }
        }
        if ($path -match '(?i)\.(fbx|png)$' -and $text.StartsWith('version https://git-lfs.github.com/spec/v1')) {
            $failures.Add("${path}: LFS placeholder instead of inspectable asset bytes")
        }
        if ($path -match '(?i)\.fbx$') {
            $temp = [IO.Path]::GetTempFileName()
            try {
                [IO.File]::WriteAllBytes($temp, $bytes)
                $result = & python (Join-Path $PSScriptRoot 'scrub_fbx.py') $temp --check 2>&1
                if ($LASTEXITCODE -ne 0) { $failures.Add("${path}: invalid FBX or native/absolute metadata needs scrubbing") }
            } finally { Remove-Item -LiteralPath $temp -Force }
        }
    }

    $changed = @(Read-GitPaths @('diff', '--cached', '--name-only', '-z'))
    if (@($changed | Where-Object { $_ -eq 'art/export-manifest.json' -or $_.StartsWith('art/export/') }).Count) {
        $manifestBytes = Read-GitBytes @('show', ':art/export-manifest.json')
        $manifest = [Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json -AsHashtable
        $exports = @(Read-GitPaths @('ls-files', '-z', '--', 'art/export/'))
        if (-not $exports.Count) { throw 'staged export manifest has no exports' }
        foreach ($path in @($exports + @($manifest.Keys) | Sort-Object -Unique)) {
            if ($path -notin $exports -or -not $manifest.ContainsKey($path)) {
                $failures.Add("${path}: missing or extra staged export")
                continue
            }
            $digest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData((Read-GitBytes @('show', ":$path")))).ToLowerInvariant()
            if ($digest -cne $manifest[$path]) { $failures.Add("${path}: staged export hash differs") }
        }
    }
    if ($failures.Count) {
        $failures | ForEach-Object { Write-Output "PUBLIC FAIL: $_" }
        exit 1
    }
    Write-Output "PUBLIC PASS: $($paths.Count) staged files checked"
} catch {
    Write-Output "PUBLIC FAIL: $($_.Exception.Message)"
    exit 1
}
