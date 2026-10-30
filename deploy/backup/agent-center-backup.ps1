param(
    [Parameter(Mandatory = $true)][string]$KeyFile,
    [string]$Output = "backups",
    [int]$RetentionDays = 7
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
& (Join-Path $root ".venv\Scripts\python.exe") `
    (Join-Path $root "scripts\dr_backup.py") `
    --output (Join-Path $root $Output) `
    --retention-days $RetentionDays `
    --require-encryption `
    --key-file $KeyFile
