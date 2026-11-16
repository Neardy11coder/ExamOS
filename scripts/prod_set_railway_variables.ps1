param(
    [string]$HostName,
    [string]$Database = "neondb",
    [string]$Service = "backend"
)

$Host.UI.RawUI.WindowTitle = "ExamOS Production - Set Railway DATABASE_URL"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " ExamOS Production - Secure Railway DATABASE_URL Setter" -ForegroundColor Cyan
Write-Host " Target Service: $Service" -ForegroundColor DarkCyan
Write-Host " Role:           examos_app (Runtime least-privilege)" -ForegroundColor DarkCyan
Write-Host "======================================================================" -ForegroundColor Cyan

if (-not $HostName) {
    $HostName = Read-Host -Prompt "Enter Neon Production Endpoint Host (e.g. ep-xxxx.ap-southeast-1.aws.neon.tech)"
}
if (-not $HostName) {
    Write-Error "Host name cannot be empty."
    exit 1
}

$secPass = Read-Host -Prompt "Enter password for PostgreSQL role 'examos_app'" -AsSecureString
if (-not $secPass) {
    Write-Error "Password cannot be empty."
    exit 1
}

$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPass)
$plainPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

$encodedPass = [System.Uri]::EscapeDataString($plainPass)
$dbUrl = "postgresql+psycopg://examos_app:$($encodedPass)@$($HostName):5432/$($Database)?sslmode=require"

Write-Host "`nSetting Railway environment variable DATABASE_URL securely via stdin..." -ForegroundColor Yellow
$dbUrl | npx --yes --package @railway/cli railway variable set DATABASE_URL --stdin --service $Service --json

$plainPass = $null
$dbUrl = $null

Write-Host "`n[SUCCESS] Production DATABASE_URL set successfully on Railway service '$Service'!" -ForegroundColor Green
