$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$base = $PSScriptRoot
$setupLog = $null
try {
    $logDir = $env:LUNG_RT_INSTALL_LOG_DIR
    if (-not $logDir) { $logDir = Join-Path $env:LOCALAPPDATA 'RadioterapiaAI\LUNG RT\Logs' }
    [void](New-Item -ItemType Directory -Path $logDir -Force)
    $setupLog = Join-Path $logDir ('LUNG_RT_INSTALL-' + [guid]::NewGuid().ToString('N') + '.log')
    Start-Transcript -LiteralPath $setupLog | Out-Null
    Write-Host ('Log da instalação: ' + $setupLog)
} catch {
    $setupLog = $null
    Write-Warning ('Não foi possível criar o log: ' + $_.Exception.Message)
}

function Stop-SetupLog {
    if ($setupLog) { Stop-Transcript | Out-Null }
}

function Write-SetupFailure($failure) {
    Write-Host ('Não foi possível concluir: ' + $failure.Exception.Message) -ForegroundColor Yellow
    if ($setupLog) { Write-Host ('Log da instalação: ' + $setupLog) }
    Stop-SetupLog
}

trap {
    Write-SetupFailure $_
    exit 1
}

$required = @('TERMS.txt', 'install.py', 'radai_lung_install.py', 'release-manifest.json',
    'code\module.json', 'suite-setup.zip', 'suite-setup.sha256')
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $base $_) -PathType Leaf) })
if ($missing.Count) {
    throw ('PACKAGE_INCOMPLETE. Use Extrair Tudo no ZIP do SETUP e execute START_HERE.cmd na pasta extraída. Arquivos ausentes: ' + ($missing -join ', '))
}

# Setup window
$setupUi = $null
if ($base) {
    $catalog = Join-Path $base 'installer-i18n.json'
    if (Test-Path -LiteralPath $catalog -PathType Leaf) {
        try {
            $translations = Get-Content -LiteralPath $catalog -Raw -Encoding UTF8 | ConvertFrom-Json
            $locale = $env:LUNG_RT_LANGUAGE
            if (-not $locale) { $locale = [Globalization.CultureInfo]::CurrentUICulture.Name }
            $locale = ($locale -split '[-_]')[0].ToLowerInvariant()
            if ($locale -eq 'pt') { $locale = 'pt-BR' }
            if ($locale -eq 'zh') { $locale = 'zh-CN' }
            $row = $translations.PSObject.Properties[$locale]
            if (-not $row) { $row = $translations.PSObject.Properties['en'] }
            if ($row) { $setupUi = $row.Value }
        } catch {
            Write-Warning ('INSTALLER_I18N: ' + $_.Exception.Message)
        }
    }
}
function SetupText([string]$key, [string]$fallback) {
    if ($setupUi) {
        $value = $setupUi.PSObject.Properties[$key]
        if ($value -and $value.Value) { return [string]$value.Value }
    }
    return $fallback
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$script:chosen = ''
$script:offline = ''
$script:reports = $false
$script:suite = ''
$terms = Get-Content -LiteralPath (Join-Path $base 'TERMS.txt') -Raw -Encoding UTF8
$form = New-Object System.Windows.Forms.Form
$form.Text = 'LUNG RT | Local Suite'
$form.Size = New-Object System.Drawing.Size(780,720)
$form.StartPosition = 'CenterScreen'
$form.BackColor = [System.Drawing.Color]::FromArgb(12,21,35)
$form.ForeColor = [System.Drawing.Color]::FromArgb(228,238,248)
$form.Font = New-Object System.Drawing.Font('Segoe UI',10)
$form.MinimumSize = $form.Size
function LabelAt([string]$text,[int]$x,[int]$y,[int]$w,[int]$h) {
    $c = New-Object System.Windows.Forms.Label
    $c.Text = $text; $c.SetBounds($x,$y,$w,$h); $form.Controls.Add($c); return $c
}
function ButtonAt([string]$text,[int]$x,[int]$y,[int]$w) {
    $c = New-Object System.Windows.Forms.Button
    $c.Text=$text; $c.SetBounds($x,$y,$w,38)
    $c.FlatStyle='Flat'; $c.BackColor=[System.Drawing.Color]::FromArgb(28,52,69)
    $form.Controls.Add($c); return $c
}
$header = LabelAt 'LUNG RT' 24 18 700 42
$header.Font = New-Object System.Drawing.Font('Segoe UI',24,[System.Drawing.FontStyle]::Bold)
[void](LabelAt (SetupText 'intro' 'Escolha os pesos extras para instalar. O Pacote para levar inclui todos os pesos CT + RX (~6,38 GB). O código é atualizado pela Local Suite.') 26 68 710 48)
[void](LabelAt (SetupText 'suiteFolder' 'Pasta da Local Suite (o Python existente será reutilizado)') 26 119 700 25)
$folder = New-Object System.Windows.Forms.TextBox
$folder.SetBounds(26,148,604,29);$folder.Text=Join-Path $env:SystemDrive 'RADIOTERAPIA_AI\LOCAL_SUITE';$form.Controls.Add($folder)
$browse = ButtonAt (SetupText 'browse' 'Pasta…') 639 143 94
$browse.Add_Click({$dialog=New-Object System.Windows.Forms.FolderBrowserDialog;$dialog.Description=(SetupText 'folderTitle' 'Pasta da Local Suite');$dialog.SelectedPath=$folder.Text;if($dialog.ShowDialog()-eq 'OK'){$folder.Text=$dialog.SelectedPath};$dialog.Dispose()})
$report = New-Object System.Windows.Forms.CheckBox
$report.SetBounds(26,185,700,54);$report.Text=(SetupText 'reports' 'Pré-laudos locais CT + RX (~6,38 GB): NVReason CT INT4 + MedGemma 1.5 4B Q4')
$report.Checked=$false;$form.Controls.Add($report)
[void](LabelAt (SetupText 'reportDefault' 'Laudos desligados (=0). CT: GPU ≥ 6 GB/WebGPU. RX: CPU, RAM ≥ 8 GB.') 26 239 705 30)
$box=New-Object System.Windows.Forms.RichTextBox
$box.SetBounds(26,276,707,259);$box.ReadOnly=$true;$box.Text=$terms
$box.BackColor=[System.Drawing.Color]::FromArgb(19,31,47);$box.ForeColor=$form.ForeColor;$box.DetectUrls=$true
$box.Add_LinkClicked({param($sender,$event) Start-Process -FilePath $event.LinkText -WindowStyle Hidden})
$form.Controls.Add($box)
$accept=New-Object System.Windows.Forms.CheckBox
$accept.SetBounds(26,547,708,44);$accept.Text=(SetupText 'accept' 'Li e aceito os termos e as licenças dos componentes que serão preparados.');$form.Controls.Add($accept)
$install=ButtonAt (SetupText 'install' 'Instalar / atualizar') 26 604 212
$offline=ButtonAt (SetupText 'offline' 'Preparar pacote offline') 251 604 242
$exit=ButtonAt (SetupText 'close' 'Fechar') 541 604 192
$install.Enabled=$false;$offline.Enabled=$false
$accept.Add_CheckedChanged({$install.Enabled=$accept.Checked;$offline.Enabled=$accept.Checked})
$install.Add_Click({$script:chosen='install';$script:suite=$folder.Text;$script:reports=$report.Checked;$form.Close()})
$offline.Add_Click({$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description=(SetupText 'offlineFolder' 'Escolha uma pasta vazia para levar o plugin à clínica');if($d.ShowDialog()-eq 'OK'){$script:offline=$d.SelectedPath;$script:suite=$folder.Text;$script:reports=$report.Checked;$script:chosen='offline';$form.Close()};$d.Dispose()})
$exit.Add_Click({$form.Close()})
[void]$form.ShowDialog()
$form.Dispose()
if(-not $script:chosen){Stop-SetupLog;exit 0}
try {
    $suitePath=[System.IO.Path]::GetFullPath($script:suite.Trim().Trim('"'))
    if($suitePath.TrimEnd('\') -eq [System.IO.Path]::GetPathRoot($suitePath).TrimEnd('\')){throw 'Escolha uma pasta dentro do disco, não a raiz.'}
    if($script:chosen -eq 'install') {
    $stamp=Join-Path $suitePath 'entrega.txt'
    if(Test-Path -LiteralPath $stamp -PathType Leaf) {
        $versionLine=Get-Content -LiteralPath $stamp | Where-Object {$_ -match '^VERSAO='} | Select-Object -First 1
        $minimum = (Get-Content -LiteralPath (Join-Path $base 'code\module.json') -Raw -Encoding UTF8 | ConvertFrom-Json).host_min_version
        if(-not $versionLine -or [version]($versionLine.Split('=')[1].Trim()) -lt [version]$minimum) {throw ('Atualize a Local Suite existente para ' + $minimum + ' pelo instalador da base e abra este START HERE novamente.')}
    } elseif(Test-Path -LiteralPath $suitePath) {
        $owned=(Test-Path -LiteralPath (Join-Path $suitePath '.lung-bootstrap')) -or (Test-Path -LiteralPath (Join-Path $suitePath '_instalacao\_motor_comecou.txt'))
        if(-not $owned -and @(Get-ChildItem -LiteralPath $suitePath -Force).Count -gt 0) {throw 'Escolha uma pasta vazia para a nova base ou uma Local Suite compatível já instalada.'}
    }
    }
    Write-Host 'LUNG RT — preparo local' -ForegroundColor Cyan
    Write-Host '1. Conferindo a base e o Python existente...'
    $python=Join-Path $suitePath 'python\python.exe'
    if(-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        if($script:chosen -eq 'offline'){throw (SetupText 'offlinePython' 'Para montar o pacote, aponte a pasta de uma Local Suite instalada. O preparo offline não baixa Python nem pesos de segmentação.')}
        $pyTarget=Join-Path $suitePath 'python'
        [void](New-Item -ItemType Directory -Path $pyTarget -Force)
        Set-Content -LiteralPath (Join-Path $suitePath '.lung-bootstrap') -Value 'LUNG RT portable runtime preparation' -Encoding ASCII
        $pyZip=Join-Path $env:TEMP ('lung-python-'+[guid]::NewGuid().ToString('N')+'.zip')
        Write-Host '2. Esta é uma base nova: baixando Python portátil 3.10.11...'
        [System.Net.ServicePointManager]::SecurityProtocol=[System.Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip' -OutFile $pyZip
        $hash=(Get-FileHash -LiteralPath $pyZip -Algorithm SHA256).Hash.ToLowerInvariant()
        if($hash -ne '608619f8619075629c9c69f361352a0da6ed7e62f83a0e19c63e0ea32eb7629d'){throw 'O download do Python não confere. A instalação não continua.'}
        Expand-Archive -LiteralPath $pyZip -DestinationPath $pyTarget -Force
        Get-ChildItem -LiteralPath $pyTarget -Filter 'python*._pth' | ForEach-Object {
            $lines = @(Get-Content -LiteralPath $_.FullName) -replace '^#\s*import site', 'import site'
            if ($lines -notcontains 'import site') { $lines += 'import site' }
            if ($lines -notcontains 'Lib\site-packages') { $lines += 'Lib\site-packages' }
            Set-Content -LiteralPath $_.FullName -Value $lines -Encoding ASCII
        }
        [void](New-Item -ItemType Directory -Path (Join-Path $pyTarget 'Lib\site-packages') -Force)
        Remove-Item -LiteralPath $pyZip -Force
        $python=Join-Path $pyTarget 'python.exe'
    } else {Write-Host '2. Python da Local Suite encontrado. Nenhum Python será baixado ou substituído.'}
    $runArgs=@('-I','-B','-X','utf8',(Join-Path $base 'install.py'),'--suite-root',$suitePath,'--accept-terms')
    if($script:reports){$runArgs+='--reports'}
    if($script:chosen -eq 'offline'){$runArgs+=@('--offline',$script:offline)}
    Write-Host '3. Conferindo código, recursos e destino. Acompanhe o progresso abaixo...'
    $previousErrorAction = $ErrorActionPreference
    $previousOutputEncoding = [Console]::OutputEncoding
    try {
        $ErrorActionPreference = 'Continue'
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
        & $python @runArgs 2>&1 | ForEach-Object { Write-Host $_ }
        $pythonExit = $LASTEXITCODE
    } finally {
        [Console]::OutputEncoding = $previousOutputEncoding
        $ErrorActionPreference = $previousErrorAction
    }
    if ($pythonExit -ne 0) { throw ('O preparo parou. Código do instalador: ' + $pythonExit + '. O motivo está no log acima.') }
    if($script:chosen -eq 'install' -and (Test-Path -LiteralPath (Join-Path $suitePath 'radai_lancador.py'))) {
        $shell=New-Object -ComObject WScript.Shell
        $shortcut=$shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'LUNG RT.lnk'))
        $shortcut.TargetPath=Join-Path $suitePath 'python\pythonw.exe'
        $port=8777
        $config=Join-Path $suitePath 'radai_watcher.config'
        if(Test-Path -LiteralPath $config){foreach($line in Get-Content -LiteralPath $config){if($line -match '^PORT\s*=\s*([0-9]+)' -and [int]$Matches[1] -gt 0 -and [int]$Matches[1] -lt 65536){$port=[int]$Matches[1]}}}
        $shortcut.Arguments='-B "'+(Join-Path $suitePath 'radai_lancador.py')+'" --url http://127.0.0.1:'+$port+'/lung'
        $shortcut.WorkingDirectory=$suitePath;$shortcut.Description='LUNG RT — Local Suite';$shortcut.Save()
    }
    Write-Host 'Pedido concluído. Se houve manutenção, acompanhe a janela externa até a reabertura.' -ForegroundColor Green
} catch {
    Write-SetupFailure $_
    exit 1
}
Stop-SetupLog
[void](Read-Host (SetupText 'exitPrompt' 'Pressione Enter para fechar'))
