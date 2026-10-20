# Shares Centurion's machine-wide cap of three Blender instances. Each instance gets a third of the cores
# less a reserve, at below-normal priority. Named mutexes release abandoned slots after a killed run.
# Usage: pwsh -File tools/Run-Blender.ps1 <blender args...>
# Blender's arguments come from the raw command line: a param block makes PowerShell parse Blender's flags (--out matches
# -OutVariable), and even $args drops the `--` that separates Blender's flags from the script's.
$raw = [Environment]::GetCommandLineArgs()
$self = [Array]::FindIndex($raw, [Predicate[string]] { param($a) $a -like '*Run-Blender.ps1' })
$BlenderArgs = if ($self -ge 0 -and $self -lt $raw.Count - 1) { $raw[($self + 1)..($raw.Count - 1)] } else { @() }

$ErrorActionPreference = 'Stop'
$blender = 'C:/Program Files (x86)/Steam/steamapps/common/Blender/blender.exe'
$slots = 3
$reserveCores = 4
$mutexes = [System.Threading.Mutex[]](0..($slots - 1) | ForEach-Object { [System.Threading.Mutex]::new($false, "Global\CenturionBlenderSlot$_") })
try { $held = [System.Threading.WaitHandle]::WaitAny($mutexes) }
catch {
    $e = $_.Exception
    while ($e -and $e -isnot [System.Threading.AbandonedMutexException]) { $e = $e.InnerException }
    if (-not $e) { throw }
    $held = $e.MutexIndex
}
try {
    $info = [System.Diagnostics.ProcessStartInfo]::new($blender)
    $info.UseShellExecute = $false
    $info.ArgumentList.Add('--threads')
    $info.ArgumentList.Add([string][math]::Max(1, [math]::Floor(([Environment]::ProcessorCount - $reserveCores) / $slots)))
    foreach ($a in $BlenderArgs) { $info.ArgumentList.Add($a) }
    $process = [System.Diagnostics.Process]::Start($info)
    $process.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal
    $process.WaitForExit()
    $code = $process.ExitCode
}
finally {
    $mutexes[$held].ReleaseMutex()
    foreach ($mutex in $mutexes) { $mutex.Dispose() }
}
exit $code
