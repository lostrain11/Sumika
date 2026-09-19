[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][string]$Destination,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Fa-f0-9]{64}$')][string]$Sha256,
    [switch]$Shortcut
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 inherits legacy .NET path limits on clean Windows.
# Opt in for this process only; do not change machine registry or OS policy.
[AppContext]::SetSwitch('Switch.System.IO.UseLegacyPathHandling', $false)
[AppContext]::SetSwitch('Switch.System.IO.BlockLongPaths', $false)
function Get-ExtendedPath([string]$Path) {
    if ($Path.StartsWith('\\?\')) { return $Path }
    if ($Path.StartsWith('\\')) { return '\\?\UNC\' + $Path.Substring(2) }
    return '\\?\' + $Path
}

$archivePath = (Resolve-Path -LiteralPath $Archive -ErrorAction Stop).Path
$destinationPath = [IO.Path]::GetFullPath($Destination)
$hashStream = [IO.File]::OpenRead($archivePath)
try {
$hasher = [Security.Cryptography.SHA256]::Create()
try { $actual = [BitConverter]::ToString($hasher.ComputeHash($hashStream)).Replace('-','') }
finally { $hasher.Dispose() }
if ($actual -ne $Sha256.ToUpperInvariant()) { throw "Archive SHA-256 mismatch" }
if (Test-Path -LiteralPath $destinationPath) {
    throw 'Destination already exists; choose a new versioned directory that does not exist'
}
$parent = Split-Path -Parent $destinationPath
if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'Destination parent must exist' }
if ($Shortcut) {
    $link = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Sumika.lnk'
    if (Test-Path -LiteralPath $link) { throw 'Existing shortcut will not be overwritten' }
}
if (-not $PSCmdlet.ShouldProcess($destinationPath, 'Install Sumika portable package')) {
    Write-Output (ConvertTo-Json @{ status='not-installed'; destination=$destinationPath })
    return
}
# Stage beside the destination, never in the system TEMP directory on C:.
# Retain failed staging for inspection; this installer never deletes files.
$temp = Join-Path $parent ('sumika-install-' + [guid]::NewGuid().ToString('N'))
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
# Keep the same read-only, non-write/non-delete-shared handle from hashing
# through extraction. A second path lookup would admit a replacement ZIP.
$hashStream.Position = 0
$zip = [IO.Compression.ZipArchive]::new($hashStream, [IO.Compression.ZipArchiveMode]::Read, $true)
try {
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $entries = [Collections.Generic.List[object]]::new()
    $size = [long]0
    foreach ($entry in $zip.Entries) {
        $name = $entry.FullName.Replace('\','/')
        while ($name.StartsWith('./')) { $name = $name.Substring(2) }
        if (-not $name) { continue }
        $parts = $name.TrimEnd('/').Split('/')
        if ($name.StartsWith('/') -or $name.Contains(':') -or
            ($parts | Where-Object { $_ -eq '..' -or $_ -eq '.' -or $_ -eq '' -or $_ -match '[. ]$|[<>"|?*\x00-\x1f\x7f]' -or $_ -match '^(?i:con|prn|aux|nul|conin\$|conout\$|com[1-9\u00b9\u00b2\u00b3]|lpt[1-9\u00b9\u00b2\u00b3]) *(?:\.|$)' })) {
            throw 'Unsafe archive path'
        }
        if ($parts[0] -notin @('Sumika.exe','package-manifest.json','tools','ui','extensions','sumika_next','runtime','licenses')) {
            throw 'Archive contains a non-release root'
        }
        if ($parts | Where-Object {
            $_ -in @('.sumika-next','.sumika-continuity','.git','__pycache__','.pytest_cache','.env','env.ps1') -or
            $_ -like '.env.*' -or $_ -like '*.update-*' -or $_ -match '\.(sqlite3|db|log|pyc|pem|key)$'
        }) { throw 'Archive contains runtime data or credentials' }
        if ((($entry.ExternalAttributes -shr 16) -band 61440) -eq 40960) { throw 'Archive links are not supported' }
        if (-not $names.Add($name.TrimEnd('/'))) { throw 'Duplicate archive path' }
        $size += $entry.Length
        if ($size -gt 8GB -or $names.Count -gt 300000) { throw 'Archive exceeds installation limits' }
        $entries.Add(@{ entry=$entry; name=$name })
    }
    if (-not $names.Contains('Sumika.exe') -or -not $names.Contains('package-manifest.json')) {
        throw 'Archive is missing package-manifest.json or Sumika.exe'
    }
    # Validate archive bytes before extraction. Never run a verifier from the
    # untrusted package, and do not require Python to validate an installation.
    $manifestEntry = @($entries | Where-Object { $_.name -ceq 'package-manifest.json' })
    if ($manifestEntry.Count -ne 1 -or $manifestEntry[0].entry.Length -gt 64MB) {
        throw 'Invalid or oversized package manifest'
    }
    $reader = [IO.StreamReader]::new($manifestEntry[0].entry.Open())
    try { $inventory = $reader.ReadToEnd() | ConvertFrom-Json }
    finally { $reader.Dispose() }
    if ($inventory.kind -cne 'portable-staging' -or $inventory.schema_version -ne 2 -or
        $inventory.files -isnot [Array] -or $inventory.files.Count -eq 0) {
        throw 'A version 2 file inventory is required'
    }
    $expected = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($row in $inventory.files) {
        if ($row.path -isnot [string] -or $row.path.Contains('\') -or
            $row.path -eq 'package-manifest.json' -or
            $row.sha256 -isnot [string] -or $row.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            ($row.size -isnot [int] -and $row.size -isnot [long]) -or $row.size -lt 0) {
            throw 'Invalid inventory entry'
        }
        if ($expected.ContainsKey($row.path)) { throw 'Duplicate inventory path' }
        $expected.Add($row.path, $row)
    }
    # A declared file may not also be an ancestor of another declared file
    # (ui/Asset versus ui/asset/icon.png). Reject that here, before any
    # staging directory exists and before a single entry is extracted.
    # Shared parent directories that are not themselves declared are valid.
    foreach ($row in $inventory.files) {
        $parts = $row.path.TrimEnd('/').Split('/')
        for ($depth = 1; $depth -lt $parts.Count; $depth++) {
            $ancestor = [string]::Join('/', $parts[0..($depth - 1)])
            if ($expected.ContainsKey($ancestor)) {
                throw 'Inventory path is both a file and a directory'
            }
        }
    }
    foreach ($required in @('Sumika.exe','tools/start_sumika.ps1','tools/start_ui_bridge.ps1',
                            'ui/server.py','sumika_next/cli.py','runtime/dsh/release.json')) {
        if (-not $expected.ContainsKey($required)) { throw 'Required release file missing' }
    }
    $verifiedCount = 0
    foreach ($item in $entries) {
        if ($item.name.EndsWith('/') -or $item.name -ceq 'package-manifest.json') { continue }
        if (-not $expected.ContainsKey($item.name)) { throw 'Archive file not in inventory' }
        $row = $expected[$item.name]
        if ($row.path -cne $item.name -or $row.size -ne $item.entry.Length) {
            throw 'Inventory path or size mismatch'
        }
        $stream = $item.entry.Open()
        $fileHasher = [Security.Cryptography.SHA256]::Create()
        try { $fileHash = [BitConverter]::ToString($fileHasher.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
        finally { $stream.Dispose(); $fileHasher.Dispose() }
        if ($fileHash -cne $row.sha256) { throw 'Inventory file hash mismatch' }
        $verifiedCount++
    }
    if ($verifiedCount -ne $expected.Count) { throw 'Inventory file absent from archive' }
    New-Item -ItemType Directory -Path $temp | Out-Null
    foreach ($item in $entries) {
        $target = Get-ExtendedPath ([IO.Path]::Combine($temp, $item.name.Replace('/', '\')))
        if ($item.name.EndsWith('/')) {
            [IO.Directory]::CreateDirectory($target) | Out-Null
        } else {
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($item.entry, $target, $false)
        }
    }
    $manifest = Join-Path $temp 'package-manifest.json'
    $launcher = Join-Path $temp 'Sumika.exe'
    if (-not (Test-Path -LiteralPath $manifest) -or -not (Test-Path -LiteralPath $launcher)) {
        throw 'Archive is missing package-manifest.json or Sumika.exe'
    }
    if (Test-Path -LiteralPath $destinationPath) {
        throw 'Destination appeared during extraction; staged installation retained without publication'
    }
    # Same-parent directory rename publishes the complete tree, or fails while
    # leaving staging intact. Never merge into even an empty existing folder.
    [IO.Directory]::Move((Get-ExtendedPath $temp), (Get-ExtendedPath $destinationPath))
        if ($Shortcut) {
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut($link)
            $shortcut.TargetPath = Join-Path $destinationPath 'Sumika.exe'
            $shortcut.WorkingDirectory = $destinationPath
            $shortcut.Save()
        }
    Write-Output (ConvertTo-Json @{ status='installed'; destination=$destinationPath; shortcut=[bool]$Shortcut })
} finally {
    $zip.Dispose()
}
} finally {
    $hashStream.Dispose()
}
