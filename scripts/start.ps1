param(
    [switch]$Console, [switch]$Diagnose, [switch]$Stop, [switch]$Restart,
    [ValidateRange(0, 86400)][double]$RunFor = 0, [string]$Snapshot = ''
)
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDir
$runtimeDir = Join-Path $projectDir '.runtime'
[IO.Directory]::CreateDirectory($runtimeDir) | Out-Null
$logPath = Join-Path $runtimeDir 'launcher.log'
function Write-LaunchLog([string]$message) {
    Add-Content -LiteralPath $logPath -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $message)
}
function Find-Python {
    # py.exe 本身可能已失去安装登记；它的 stderr 不能阻止其他候选检查。
    $ErrorActionPreference = 'Continue'
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $candidates.Add((Join-Path $projectDir '.venv\Scripts\python.exe'))
    $candidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'))
    foreach ($registry in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        if (Test-Path -LiteralPath $registry) {
            foreach ($version in (Get-ChildItem -LiteralPath $registry | Sort-Object PSChildName -Descending)) {
                $install = Join-Path $version.PSPath 'InstallPath'
                if (Test-Path -LiteralPath $install) {
                    $folder = (Get-Item -LiteralPath $install).GetValue('')
                    if ($folder) { $candidates.Add((Join-Path $folder 'python.exe')) }
                }
            }
        }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        foreach ($version in @('-3.11', '-3')) {
            $selected = & $launcher.Source $version -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $selected) { $candidates.Add([string]($selected | Select-Object -Last 1)) }
        }
    }
    $onPath = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($onPath -and $onPath.Source -notlike '*WindowsApps*') { $candidates.Add($onPath.Source) }
    $seen = @{}
    foreach ($candidate in $candidates) {
        if ($seen.ContainsKey($candidate) -or -not (Test-Path -LiteralPath $candidate)) { continue }
        $seen[$candidate] = $true
        $output = & $candidate -c 'from PyQt6 import QtWidgets,QtWebEngineWidgets,QtMultimedia; import aiohttp,websockets,yaml,loguru,edge_tts,requests,webrtcvad; print(1)' 2>&1
        if ($LASTEXITCODE -eq 0) { return $candidate }
        Write-LaunchLog ('Python unavailable: ' + $candidate + ' / ' + (($output | Out-String).Trim()))
    }
    throw '没有找到依赖完整的 Python。请先运行 scripts\install.ps1；详细原因见 .runtime\launcher.log。'
}
function Read-Status([string]$base) {
    try {
        $response = Invoke-RestMethod -Uri ($base + '/api/status') -TimeoutSec 2
        if ($response.success -and $response.data.name -eq 'Hsin') { return $response }
    } catch { }
    return $null
}
try {
    $python = Find-Python
    $probeOutput = & $python -m tools.launch_diagnostics 2>&1
    if ($LASTEXITCODE -ne 0) { throw ('启动预检失败：' + ($probeOutput | Out-String).Trim()) }
    $probe = ($probeOutput | Select-Object -Last 1) | ConvertFrom-Json
    Write-LaunchLog ('Python: ' + $python)
    if ($Diagnose) { $probe | ConvertTo-Json; exit 0 }
    $base = ''
    if ($probe.http_enabled) {
        $address = $probe.http_host
        if ($address -eq '::1') { $address = '[::1]' }
        $base = 'http://' + $address + ':' + $probe.http_port
    }
    $existing = if ($base) { Read-Status $base } else { $null }
    if ($Stop -or $Restart) {
        if ($existing) {
            $reply = Invoke-RestMethod -Uri ($base + '/api/command') -Method Post -ContentType 'application/json' -Body '{"type":"window","data":{"action":"quit"}}' -TimeoutSec 5
            if (-not $reply.success) { throw '请先从托盘退出旧版本后重试。' }
            $deadline = (Get-Date).AddSeconds(15)
            $lockPath = Join-Path $probe.runtime 'hsin.lock'
            while ((Get-Date) -lt $deadline -and ((Read-Status $base) -or (Test-Path -LiteralPath $lockPath))) { Start-Sleep -Milliseconds 200 }
            if ((Read-Status $base) -or (Test-Path -LiteralPath $lockPath)) { throw '等待退出超时，请查看 .runtime\hsin.log。' }
            $existing = $null
            Write-LaunchLog 'Hsin stopped cleanly'
        } elseif (-not $base) { throw '本机控制接口未启用，请从托盘退出心。' }
        if ($Stop) { Write-Output '心已停止。'; exit 0 }
    }
    if ($existing) {
        Invoke-RestMethod -Uri ($base + '/api/window') -Method Post -ContentType 'application/json' -Body '{"action":"show"}' -TimeoutSec 5 | Out-Null
        Write-LaunchLog 'Existing Hsin shown; duplicate launch skipped'
        Write-Output '心已经在运行，已显示窗口。'
        exit 0
    }
    $appArguments = @('-m', 'src.main')
    if ($RunFor -gt 0) { $appArguments += @('--run-for', $RunFor.ToString([Globalization.CultureInfo]::InvariantCulture)) }
    if ($Snapshot) { $appArguments += @('--snapshot', $Snapshot) }
    if ($Console) { & $python @appArguments; exit $LASTEXITCODE }
    $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $python }
    $argumentLine = ($appArguments | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $env:PYTHONUTF8 = '1'
    $appProcess = Start-Process -FilePath $pythonw -ArgumentList $argumentLine -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'launcher.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'launcher.stderr.log')
    Write-LaunchLog ('Started PID ' + $appProcess.Id)
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        $appProcess.Refresh()
        if ($appProcess.HasExited) { throw '心未能启动，请查看 .runtime\launcher.stderr.log 和 .runtime\hsin.log。' }
        if ($base -and (Read-Status $base)) { Write-Output ('心已启动，进程 ' + $appProcess.Id); exit 0 }
        if (-not $base) { Write-Output ('心已启动，进程 ' + $appProcess.Id); exit 0 }
    }
    throw '未能确认心的本机接口，请查看 .runtime\launcher.stderr.log 和 .runtime\hsin.log。'
} catch {
    $message = $_.Exception.Message
    Write-LaunchLog ('ERROR: ' + $message)
    Write-Output $message
    if (-not $Console -and -not $Diagnose) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show($message, '心启动失败') | Out-Null
    }
    exit 1
}
