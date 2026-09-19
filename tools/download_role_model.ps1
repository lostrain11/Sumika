param(
    [Parameter(Mandatory=$true)][string]$Repository,
    [Parameter(Mandatory=$true)][string]$Filename,
    [string]$Destination = 'E:\Models\Sumika\role-models'
)
$ErrorActionPreference = 'Stop'
if ($Filename -ne [IO.Path]::GetFileName($Filename)) { throw 'Filename must be a basename' }
$metadata = Invoke-RestMethod "https://huggingface.co/api/models/${Repository}?blobs=true" -TimeoutSec 30
$file = @($metadata.siblings | Where-Object rfilename -eq $Filename)
if ($file.Count -ne 1 -or -not $file[0].lfs.sha256) { throw 'Missing upstream LFS hash' }
$hash = $file[0].lfs.sha256
$size = [long]$file[0].size
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$target = Join-Path $Destination $Filename
$partial = "$target.partial"
if (Test-Path -LiteralPath $target) {
    if ((Get-FileHash -LiteralPath $target).Hash -ne $hash) { throw 'Existing file differs; refusing overwrite' }
} else {
    $drive = Get-PSDrive ([IO.Path]::GetPathRoot($target).TrimEnd('\').TrimEnd(':'))
    if ($drive.Free -lt ($size + 2GB)) { throw 'Insufficient free space with 2 GiB reserve' }
    $url = "https://hf-mirror.com/$Repository/resolve/$($metadata.sha)/$Filename"
    & curl.exe -sS -L --fail --connect-timeout 20 --max-time 1800 --retry 2 -C - -o $partial $url
    if ($LASTEXITCODE -ne 0) { throw 'Transfer failed; partial file retained for resume' }
    if ((Get-Item -LiteralPath $partial).Length -ne $size -or (Get-FileHash -LiteralPath $partial).Hash -ne $hash) { throw 'Artifact integrity check failed' }
    Move-Item -LiteralPath $partial -Destination $target
}
$receipt = [ordered]@{ repository=$Repository; revision=$metadata.sha; filename=$Filename; bytes=$size; sha256=$hash; card_license=$metadata.cardData.license; base_model=$metadata.cardData.base_model; downloaded_at=[DateTime]::UtcNow.ToString('o'); path=$target; verified=$true }
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$target.receipt.json" -Encoding utf8
$receipt | ConvertTo-Json -Depth 6
