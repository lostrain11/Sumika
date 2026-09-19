param([switch]$Execute)
$ErrorActionPreference='Stop'
$destinationRoot='E:\Models'
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$evidence=Join-Path $destinationRoot "migration-records\$stamp"
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
$pairs=@(
  @('E:\AI\OllamaModels','E:\Models\Ollama\main'),
  @('E:\AI\OllamaModels-Neon','E:\Models\Ollama\neon'),
  @('C:\Users\Lostrain.DESKTOP-43S7UNP\.ollama\models','E:\Models\Ollama\legacy-minicpm'),
  @('E:\Models\Sumika\role-models','E:\Models\GGUF\role-models'),
  @('D:\Models\Sumika\role-models','E:\Models\GGUF\minicpm'),
  @('D:\Code\Sumika\.sumika-next\embedding-models','E:\Models\Embeddings\sumika'),
  @('D:\Code\Sumika\.sumika-next\voice-models','E:\Models\Speech\sumika'),
  @('D:\Code\Sumika\.sumika-next\role-dsh-bbp8o5np\work\models','E:\Models\Embeddings\acceptance-bbp8o5np'),
  @('D:\Code\Sumika\.sumika-next\role-dsh-c15b29d4f3c04d7c887af32d10e45261\work\models','E:\Models\Embeddings\acceptance-c15b29d4')
)
if(Get-CimInstance Win32_Process -Filter "Name='ollama.exe' OR Name='llama-server.exe'"){throw 'Model runtime active; no migration performed'}
$records=@()
foreach($pair in $pairs){
  $source=[IO.Path]::GetFullPath($pair[0]);$target=[IO.Path]::GetFullPath($pair[1])
  if(-not $target.StartsWith($destinationRoot+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Target outside model root'}
  if(-not(Test-Path -LiteralPath $source)){throw "Missing source: $source"}
  $sourceItem=Get-Item -LiteralPath $source
  if($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint){throw "Source is a link: $source"}
  if(Test-Path -LiteralPath $target){throw "Target exists: $target"}
  $entries=@(Get-ChildItem -LiteralPath $source -Recurse -Force)
  if($entries | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}){throw "Nested link requires separate review: $source"}
  $manifest=@($entries | Where-Object {-not $_.PSIsContainer} | ForEach-Object {
    [pscustomobject]@{path=$_.FullName.Substring($source.Length+1);bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  })
  $record=[pscustomobject]@{source=$source;target=$target;files=$manifest;state='inventoried'}
  $records+=$record
}
$records | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'manifest.json') -Encoding UTF8
Write-Output "Preflight: $($records.Count) roots; evidence $evidence"
if(-not $Execute){return}
foreach($record in $records){
  $source=$record.source;$target=$record.target
  New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
  # Copy and verify before removing any original. The verified destination is
  # the recoverable full copy; a manifest preserves every original identity.
  Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
  foreach($f in $record.files){
    $copy=Join-Path $target $f.path
    if((Get-Item -LiteralPath $copy).Length -ne $f.bytes -or (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash -ne $f.sha256){throw "Copy mismatch: $copy"}
    if((Get-FileHash -LiteralPath (Join-Path $source $f.path) -Algorithm SHA256).Hash -ne $f.sha256){throw "Source changed during migration: $source"}
  }
  $now=@(Get-ChildItem -LiteralPath $source -Recurse -Force)
  if(($now | Where-Object {-not $_.PSIsContainer}).Count -ne $record.files.Count -or ($now | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint})){throw 'Source topology changed'}
  $resolved=(Resolve-Path -LiteralPath $source).Path
  if($resolved -ne $record.source -or -not($pairs | Where-Object {$_[0] -eq $resolved})){throw 'Source path not in explicit migration allowlist'}
  $record.state='copied_and_sha256_verified'
  $records | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'manifest.json') -Encoding UTF8
  Remove-Item -LiteralPath $resolved -Recurse -Force
  New-Item -ItemType Junction -Path $source -Target $target | Out-Null
  if((Get-Item -LiteralPath $source).LinkType -ne 'Junction'){throw 'Compatibility link not created'}
  $record.state='migrated_with_compatibility_junction'
  $records | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'manifest.json') -Encoding UTF8
  Write-Output "Verified and migrated: $source -> $target"
}
[Environment]::SetEnvironmentVariable('OLLAMA_MODELS','E:\Models\Ollama\main','User')
Write-Output "DONE: $evidence"
