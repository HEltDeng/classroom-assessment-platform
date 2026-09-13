#requires -Version 5.1

[CmdletBinding()]
param(
    [ValidateSet("Inspect", "Deploy")]
    [string]$Action = "Inspect",
    [string]$RepoRoot = "",
    [string]$WebHost = "assessment.mychangliapp.cn"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$resolvedRepo = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $resolvedRepo ".git") -PathType Container)) {
    throw "Classroom assessment Git repository is missing: $resolvedRepo"
}

function Convert-SecureValueToPlainText {
    param([Parameter(Mandatory = $true)][object]$Value)

    if ($Value -is [System.Management.Automation.PSCredential]) {
        return $Value.GetNetworkCredential().Password
    }
    if ($Value -is [System.Security.SecureString]) {
        $pointer = [System.IntPtr]::Zero
        try {
            $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
            return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        } finally {
            if ($pointer -ne [System.IntPtr]::Zero) {
                [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
            }
        }
    }
    throw "Secure credential record is invalid."
}

$recordPath = Join-Path $env:LOCALAPPDATA "MyChangli\Secrets\backend-key-sudo.clixml"
if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) {
    throw "Existing SSH/sudo secure record is missing."
}
$record = Import-Clixml -LiteralPath $recordPath
foreach ($propertyName in @("HostName", "Port", "UserName", "IdentityFile", "KeyPassphrase", "SudoPassword")) {
    if (-not $record.PSObject.Properties[$propertyName]) {
        throw "Secure record is missing '$propertyName'."
    }
}
if (-not (Test-Path -LiteralPath ([string]$record.IdentityFile) -PathType Leaf)) {
    throw "SSH private key file was not found."
}

$runtimeRoot = "D:\Codex\01_App-应用开发\001_MyChangLi-我的长理\00_Project-项目说明\Local-Automation\runtime\backend-password-runtime"
$python = Join-Path $runtimeRoot "venv\Scripts\python.exe"
$pythonScript = Join-Path $resolvedRepo "scripts\deploy.py"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The established secure deployment Python runtime is missing."
}
if (-not (Test-Path -LiteralPath $pythonScript -PathType Leaf)) {
    throw "Deployment helper is missing: $pythonScript"
}

$envNames = @(
    "CLASSROOM_SSH_HOST",
    "CLASSROOM_SSH_PORT",
    "CLASSROOM_SSH_USER",
    "CLASSROOM_SSH_KEY",
    "CLASSROOM_SSH_KEY_PASSPHRASE",
    "CLASSROOM_SSH_SUDO"
)
$previous = @{}
foreach ($name in $envNames) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
try {
    $env:CLASSROOM_SSH_HOST = [string]$record.HostName
    $env:CLASSROOM_SSH_PORT = [string]$record.Port
    $env:CLASSROOM_SSH_USER = [string]$record.UserName
    $env:CLASSROOM_SSH_KEY = [string]$record.IdentityFile
    $env:CLASSROOM_SSH_KEY_PASSPHRASE = Convert-SecureValueToPlainText $record.KeyPassphrase
    $env:CLASSROOM_SSH_SUDO = Convert-SecureValueToPlainText $record.SudoPassword

    $pythonAction = if ($Action -eq "Deploy") { "deploy" } else { "inspect" }
    & $python $pythonScript --action $pythonAction --repo $resolvedRepo --web-host $WebHost
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
} finally {
    foreach ($name in $envNames) {
        if ($null -eq $previous[$name]) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
        }
    }
}
