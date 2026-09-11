# Установка агента распознавания сканов Meridian на компьютер с LM Studio.
#
# Что делает: раскладывает агента в профиль пользователя, ставит зависимости в своё
# окружение, спрашивает токен и заводит задание в планировщике Windows. Дальше агент
# поднимается при входе в систему сам, работает без окна и перезапускается, если упадёт.
#
# Задание планировщика, а не служба: служба требует прав администратора и не видит
# LM Studio, запущенную в сеансе пользователя.
#
# Запуск: двойной клик по install.cmd рядом. Вручную:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Удаление:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall
param(
    [switch]$Uninstall,
    [string]$ServerUrl = "https://meridianai.ru",
    [string]$InstallDir = "$env:LOCALAPPDATA\MeridianOcrAgent",
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$TaskName = "Meridian OCR Agent"
$MinPython = [Version]"3.11"

function Assert-Python {
    # asyncio.TaskGroup и ExceptionGroup есть с 3.11 — старше не нужно.
    $candidate = Get-Command py -ErrorAction SilentlyContinue
    if (-not $candidate) { $candidate = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $candidate) {
        throw "Python не найден. Поставьте Python с python.org (галочка «Add to PATH») и запустите снова."
    }
    $raw = & $candidate.Source -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($LASTEXITCODE -ne 0) { throw "Не удалось спросить версию у $($candidate.Source)." }
    if ([Version]$raw -lt $MinPython) {
        throw "Нужен Python $MinPython или новее, найден $raw. Поставьте свежий с python.org."
    }
    Write-Host "Python $raw - $($candidate.Source)"
    return $candidate.Source
}

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Задание планировщика удалено."
    }
    Write-Host "Файлы остались в $InstallDir — с настройками и токеном. Удалите вручную, если нужно."
    exit 0
}

$python = Assert-Python

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "meridian_ocr_agent") -Destination $InstallDir -Recurse -Force
foreach ($helper in @("check.cmd", "once.cmd", "logs.cmd", "requirements.txt")) {
    $from = Join-Path $PSScriptRoot $helper
    if (Test-Path $from) { Copy-Item -Path $from -Destination $InstallDir -Force }
}
Write-Host "Агент установлен в $InstallDir"

# Своё окружение: агент не зависит от системного Python и ничего туда не ставит.
$venv = Join-Path $InstallDir ".venv"
if (-not (Test-Path $venv)) { & $python -m venv $venv }
$venvPython = Join-Path $venv "Scripts\python.exe"
# pythonw.exe — тот же интерпретатор без консольного окна.
$venvPythonw = Join-Path $venv "Scripts\pythonw.exe"
if (-not (Test-Path $venvPythonw)) {
    throw "В окружении нет pythonw.exe ($venvPythonw). Удалите $venv и запустите снова."
}
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $InstallDir "requirements.txt")
Write-Host "Зависимости поставлены."

# ── настройки ─────────────────────────────────────────────────────────────
$configPath = Join-Path $InstallDir "meridian-ocr-agent.json"

if (-not $Token) {
    Write-Host ""
    Write-Host "Токен агента берётся в Meridian: Админка -> «Распознавание сканов»"
    Write-Host "-> «Подключить компьютер». Он показывается ровно один раз."
    Write-Host "Если токен уже вписан, просто нажмите Enter."
    Write-Host ""
    $Token = (Read-Host "Вставьте токен агента").Trim()
}

if (Test-Path $configPath) {
    # Существующие настройки правим, а не затираем: там могли поменять DPI или модель.
    $config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Token) { $config.token = $Token }
    $config | ConvertTo-Json | Out-File -FilePath $configPath -Encoding utf8
    Write-Host "Настройки обновлены: $configPath"
} else {
    $config = [ordered]@{
        server_url            = $ServerUrl
        token                 = $Token
        lmstudio_base_url     = "http://127.0.0.1:1234/v1"
        lmstudio_api_key      = ""
        model                 = "chandra-ocr-2"
        dpi                   = 200
        concurrency           = 4
        page_timeout_seconds  = 300
        poll_interval_seconds = 60
    }
    $config | ConvertTo-Json | Out-File -FilePath $configPath -Encoding utf8
    Write-Host "Создан файл настроек: $configPath"
}

$saved = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$hasToken = [bool]$saved.token

# ── задание планировщика ──────────────────────────────────────────────────
$action = New-ScheduledTaskAction -Execute $venvPythonw `
    -Argument "-m meridian_ocr_agent" -WorkingDirectory $InstallDir

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
# Второй шанс: вход в систему бывает редко. Если агент вышел сам (например, токен отозван),
# повтор раз в 15 минут поднимет его без перезагрузки, а IgnoreNew не заведёт второго.
try {
    $repeatTrigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(15)) `
        -RepetitionInterval (New-TimeSpan -Minutes 15)
    $triggers = @($logonTrigger, $repeatTrigger)
} catch {
    Write-Host "Повторный запуск каждые 15 минут завести не удалось, остаётся запуск при входе."
    $triggers = @($logonTrigger)
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Description "Распознавание сканов Meridian локальной моделью" | Out-Null
Write-Host "Задание планировщика создано: $TaskName"

# ── проверка и запуск ─────────────────────────────────────────────────────
Write-Host ""
if (-not $hasToken) {
    Write-Host "Токен не задан, поэтому агент не запущен."
    Write-Host "Возьмите токен в админке Meridian и запустите install.cmd ещё раз."
    exit 0
}

Write-Host "Проверяю связь..."
Push-Location $InstallDir
try {
    & $venvPython -m meridian_ocr_agent --check
    $checkCode = $LASTEXITCODE
} finally {
    Pop-Location
}

Start-ScheduledTask -TaskName $TaskName
Write-Host ""
Write-Host "Агент запущен и работает в фоне. Окна у него нет — это норма."
Write-Host "На связи ли компьютер, видно в Meridian: Админка -> «Распознавание сканов»."
Write-Host "Журнал: $InstallDir\logs\agent.log (или logs.cmd там же)."

if ($checkCode -ne 0) {
    Write-Host ""
    Write-Host "Проверка прошла не полностью — смотрите строки выше."
    Write-Host "Чаще всего в LM Studio не запущен сервер или не загружена chandra-ocr-2."
    Write-Host "Агент подождёт: задачи он не берёт, пока модель не готова, и очередь не портится."
}
