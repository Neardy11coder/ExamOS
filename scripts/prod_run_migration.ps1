param(
    [string]$HostName,
    [string]$Database = "neondb",
    [string]$Role = "examos_migrator"
)

$Host.UI.RawUI.WindowTitle = "ExamOS Production - Execute Migrations"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " ExamOS Production - Secure Migration Runner" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

if (-not $HostName) {
    $HostName = Read-Host -Prompt "Enter Neon Production Endpoint Host (e.g. ep-xxxx.ap-southeast-1.aws.neon.tech)"
}
if (-not $HostName) {
    Write-Error "Host name cannot be empty."
    exit 1
}

$secPass = Read-Host -Prompt "Enter password for PostgreSQL role '$Role'" -AsSecureString
if (-not $secPass) {
    Write-Error "Password cannot be empty."
    exit 1
}

# Decrypt in unmanaged memory to build connection string
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPass)
$plainPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

$encodedPass = [System.Uri]::EscapeDataString($plainPass)
$dbUrl = "postgresql+psycopg://$($Role):$($encodedPass)@$($HostName):5432/$($Database)?sslmode=require"

# Resolve python
$pythonExe = Join-Path $PSScriptRoot "..\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python.exe"
}

# Launch Alembic upgrade head with in-memory environment variable
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $pythonExe
$psi.Arguments = "-c ""import os, alembic.config; os.chdir('backend'); alembic.config.main(['--raiseerr', '-c', 'alembic.ini', 'upgrade', 'head'])"""
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $false
$psi.RedirectStandardError = $false
$psi.WorkingDirectory = "C:\Projects\ExamOS"
$psi.EnvironmentVariables["MIGRATION_DATABASE_URL"] = $dbUrl

$plainPass = $null
$dbUrl = $null

Write-Host "`nExecuting migrations up to head revision..." -ForegroundColor Yellow
$proc = [System.Diagnostics.Process]::Start($psi)
$proc.WaitForExit()

if ($proc.ExitCode -eq 0) {
    Write-Host "`n[SUCCESS] Production migrations completed successfully!" -ForegroundColor Green
} else {
    Write-Host "`n[FAILED] Production migrations failed with exit code: $($proc.ExitCode)" -ForegroundColor Red
}

exit $proc.ExitCode
