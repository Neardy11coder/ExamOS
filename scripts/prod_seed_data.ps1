param(
    [string]$HostName,
    [string]$Database = "neondb",
    [string]$Role = "examos_migrator"
)

$Host.UI.RawUI.WindowTitle = "ExamOS Production - Seed Datasets"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " ExamOS Production - Clean Dataset Seeding Runner" -ForegroundColor Cyan
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

$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPass)
$plainPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

$encodedPass = [System.Uri]::EscapeDataString($plainPass)
$dbUrl = "postgresql+psycopg://$($Role):$($encodedPass)@$($HostName):5432/$($Database)?sslmode=require"

$pythonExe = Join-Path $PSScriptRoot "..\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python.exe"
}

# 1. Run seed_topics
Write-Host "`n[1/2] Seeding 8 authoritative taxonomy topics..." -ForegroundColor Yellow
$psi1 = New-Object System.Diagnostics.ProcessStartInfo
$psi1.FileName = $pythonExe
$psi1.Arguments = "-m app.commands.seed_topics"
$psi1.UseShellExecute = $false
$psi1.WorkingDirectory = "C:\Projects\ExamOS\backend"
$psi1.EnvironmentVariables["MIGRATION_DATABASE_URL"] = $dbUrl

$proc1 = [System.Diagnostics.Process]::Start($psi1)
$proc1.WaitForExit()
if ($proc1.ExitCode -ne 0) {
    $plainPass = $null
    $dbUrl = $null
    Write-Error "Seeding taxonomy topics failed."
    exit $proc1.ExitCode
}

# 2. Run seed_lab_dataset
Write-Host "`n[2/2] Seeding Database Performance Lab reference dataset (medium scale)..." -ForegroundColor Yellow
$psi2 = New-Object System.Diagnostics.ProcessStartInfo
$psi2.FileName = $pythonExe
$psi2.Arguments = "-m app.commands.seed_lab_dataset --size medium --seed 42"
$psi2.UseShellExecute = $false
$psi2.WorkingDirectory = "C:\Projects\ExamOS\backend"
$psi2.EnvironmentVariables["MIGRATION_DATABASE_URL"] = $dbUrl

$proc2 = [System.Diagnostics.Process]::Start($psi2)
$proc2.WaitForExit()

$plainPass = $null
$dbUrl = $null

if ($proc2.ExitCode -eq 0) {
    Write-Host "`n[SUCCESS] Production datasets seeded successfully!" -ForegroundColor Green
} else {
    Write-Host "`n[FAILED] Seeding lab dataset failed with exit code: $($proc2.ExitCode)" -ForegroundColor Red
}

exit $proc2.ExitCode
