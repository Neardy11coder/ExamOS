param(
    [string]$HostName,
    [string]$Database = "neondb",
    [string]$FacultyEmail = "faculty.admin@examos.edu"
)

$Host.UI.RawUI.WindowTitle = "ExamOS Production - Bootstrap Faculty Administrator"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " ExamOS Production - Ephemeral Faculty Bootstrap Runner" -ForegroundColor Cyan
Write-Host " Role: examos_provisioner (SECURITY DEFINER execution)" -ForegroundColor DarkCyan
Write-Host "======================================================================" -ForegroundColor Cyan

if (-not $HostName) {
    $HostName = Read-Host -Prompt "Enter Neon Production Endpoint Host (e.g. ep-xxxx.ap-southeast-1.aws.neon.tech)"
}
if (-not $HostName) {
    Write-Error "Host name cannot be empty."
    exit 1
}

$secProvPass = Read-Host -Prompt "Enter password for PostgreSQL role 'examos_provisioner'" -AsSecureString
if (-not $secProvPass) {
    Write-Error "Provisioner role password cannot be empty."
    exit 1
}

$emailInput = Read-Host -Prompt "Enter production faculty email [$FacultyEmail]"
if ($emailInput -and $emailInput.Trim()) {
    $FacultyEmail = $emailInput.Trim()
}

$secLoginPass = Read-Host -Prompt "Enter login password to assign to initial faculty account ($FacultyEmail)" -AsSecureString
if (-not $secLoginPass) {
    Write-Error "Faculty login password cannot be empty."
    exit 1
}

$bstr1 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secProvPass)
$plainProvPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr1)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr1)

$bstr2 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secLoginPass)
$plainLoginPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr2)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr2)

$encodedProvPass = [System.Uri]::EscapeDataString($plainProvPass)
$dbUrl = "postgresql+psycopg://examos_provisioner:$($encodedProvPass)@$($HostName):5432/$($Database)?sslmode=require"

$pythonExe = Join-Path $PSScriptRoot "..\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python.exe"
}

Write-Host "`nProvisioning initial production administrator via stored procedure..." -ForegroundColor Yellow

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $pythonExe
$psi.Arguments = "-m app.commands.bootstrap_faculty --email `"$FacultyEmail`" --name `"Lead Administrator`""
$psi.UseShellExecute = $false
$psi.WorkingDirectory = "C:\Projects\ExamOS\backend"
$psi.EnvironmentVariables["PROVISIONER_DATABASE_URL"] = $dbUrl
$psi.EnvironmentVariables["SEED_FACULTY_PASSWORD"] = $plainLoginPass

$plainProvPass = $null
$plainLoginPass = $null
$dbUrl = $null

$proc = [System.Diagnostics.Process]::Start($psi)
$proc.WaitForExit()

if ($proc.ExitCode -eq 0) {
    Write-Host "`n[SUCCESS] Faculty administrator ($FacultyEmail) provisioned successfully!" -ForegroundColor Green
    Write-Host "[IMPORTANT] Now execute: ALTER ROLE examos_provisioner NOLOGIN; in Neon SQL Editor to lock this role." -ForegroundColor Yellow
} else {
    Write-Host "`n[FAILED] Faculty provisioning failed with exit code: $($proc.ExitCode)" -ForegroundColor Red
}

exit $proc.ExitCode
