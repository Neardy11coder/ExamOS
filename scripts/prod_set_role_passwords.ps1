param(
    [string]$HostName,
    [string]$Database = "neondb"
)

$Host.UI.RawUI.WindowTitle = "ExamOS Production - Set Database Role Passwords"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " ExamOS Production - Secure Role Password Provisioner" -ForegroundColor Cyan
Write-Host " (Executes direct over SSL — Zero query logging in Neon Web Console)" -ForegroundColor DarkCyan
Write-Host "======================================================================" -ForegroundColor Cyan

if (-not $HostName) {
    $HostName = Read-Host -Prompt "Enter Neon Production Endpoint Host (e.g. ep-xxxx.ap-southeast-1.aws.neon.tech)"
}
if (-not $HostName) {
    Write-Error "Host name cannot be empty."
    exit 1
}

$secOwnerPass = Read-Host -Prompt "Enter password for administrative role 'neondb_owner'" -AsSecureString
if (-not $secOwnerPass) {
    Write-Error "Admin password cannot be empty."
    exit 1
}

Write-Host "`nEnter new passwords to assign to production roles:" -ForegroundColor Yellow

$secMigPass = Read-Host -Prompt "Enter password to assign to 'examos_migrator'" -AsSecureString
if (-not $secMigPass) { Write-Error "Migrator password cannot be empty."; exit 1 }

$secAppPass = Read-Host -Prompt "Enter password to assign to 'examos_app'" -AsSecureString
if (-not $secAppPass) { Write-Error "App password cannot be empty."; exit 1 }

$secProvPass = Read-Host -Prompt "Enter password to assign to 'examos_provisioner'" -AsSecureString
if (-not $secProvPass) { Write-Error "Provisioner password cannot be empty."; exit 1 }

# Decrypt in memory
$bstrOwner = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secOwnerPass)
$plainOwner = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstrOwner)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstrOwner)

$bstrMig = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secMigPass)
$plainMig = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstrMig)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstrMig)

$bstrApp = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secAppPass)
$plainApp = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstrApp)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstrApp)

$bstrProv = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secProvPass)
$plainProv = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstrProv)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstrProv)

$pythonExe = Join-Path $PSScriptRoot "..\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python.exe"
}

$pyScript = @"
import os, sys
import psycopg

host = os.environ['DB_HOST']
dbname = os.environ['DB_NAME']
owner_pass = os.environ['OWNER_PASS']
mig_pass = os.environ['MIG_PASS']
app_pass = os.environ['APP_PASS']
prov_pass = os.environ['PROV_PASS']

# Clean env immediately
del os.environ['OWNER_PASS']
del os.environ['MIG_PASS']
del os.environ['APP_PASS']
del os.environ['PROV_PASS']

try:
    conn_str = f"host={host} dbname={dbname} user=neondb_owner password={owner_pass} sslmode=require"
    with psycopg.connect(conn_str, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER ROLE examos_migrator WITH PASSWORD %s", (mig_pass,))
            cur.execute("ALTER ROLE examos_app WITH PASSWORD %s", (app_pass,))
            cur.execute("ALTER ROLE examos_provisioner WITH PASSWORD %s", (prov_pass,))
    print("[SUCCESS] Successfully configured production role passwords over direct TLS connection.")
    print("          Zero password exposure in Neon Web SQL Editor history.")
except Exception as e:
    print(f"[ERROR] Failed to set role passwords: {e}", file=sys.stderr)
    sys.exit(1)
"@

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $pythonExe
$psi.Arguments = "-c `"$pyScript`""
$psi.UseShellExecute = $false
$psi.EnvironmentVariables["DB_HOST"] = $HostName
$psi.EnvironmentVariables["DB_NAME"] = $Database
$psi.EnvironmentVariables["OWNER_PASS"] = $plainOwner
$psi.EnvironmentVariables["MIG_PASS"] = $plainMig
$psi.EnvironmentVariables["APP_PASS"] = $plainApp
$psi.EnvironmentVariables["PROV_PASS"] = $plainProv

$plainOwner = $null
$plainMig = $null
$plainApp = $null
$plainProv = $null

$proc = [System.Diagnostics.Process]::Start($psi)
$proc.WaitForExit()

exit $proc.ExitCode
