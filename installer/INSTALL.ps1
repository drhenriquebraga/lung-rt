$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$base = $PSScriptRoot
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
[void](LabelAt 'Instale como plugin ou prepare uma Local Suite compacta para rotinas pulmonares.' 26 68 710 48)
[void](LabelAt 'Pasta da Local Suite (o Python existente será reutilizado)' 26 119 700 25)
$folder = New-Object System.Windows.Forms.TextBox
$folder.SetBounds(26,148,604,29);$folder.Text=Join-Path $env:SystemDrive 'RADIOTERAPIA_AI\LOCAL_SUITE';$form.Controls.Add($folder)
$browse = ButtonAt 'Pasta…' 639 143 94
$browse.Add_Click({$dialog=New-Object System.Windows.Forms.FolderBrowserDialog;$dialog.Description='Pasta da Local Suite';$dialog.SelectedPath=$folder.Text;if($dialog.ShowDialog()-eq 'OK'){$folder.Text=$dialog.SelectedPath};$dialog.Dispose()})
$report = New-Object System.Windows.Forms.CheckBox
$report.SetBounds(26,190,700,44);$report.Text='Preparar também laudos experimentais locais (~3 GB; WebGPU, GPU ≥ 6 GB)'
$report.Checked=$false;$form.Controls.Add($report)
[void](LabelAt 'No rastreio contínuo, gerar laudos vem desligado (=0). Você poderá ativar depois.' 26 238 705 30)
$box=New-Object System.Windows.Forms.RichTextBox
$box.SetBounds(26,276,707,259);$box.ReadOnly=$true;$box.Text=$terms
$box.BackColor=[System.Drawing.Color]::FromArgb(19,31,47);$box.ForeColor=$form.ForeColor;$box.DetectUrls=$true
$box.Add_LinkClicked({param($sender,$event) Start-Process -FilePath $event.LinkText -WindowStyle Hidden})
$form.Controls.Add($box)
$accept=New-Object System.Windows.Forms.CheckBox
$accept.SetBounds(26,547,708,44);$accept.Text='Li e aceito os termos e as licenças dos componentes que serão preparados.';$form.Controls.Add($accept)
$install=ButtonAt 'Instalar / atualizar' 26 604 212
$offline=ButtonAt 'Preparar pacote offline' 251 604 242
$exit=ButtonAt 'Fechar' 541 604 192
$install.Enabled=$false;$offline.Enabled=$false
$accept.Add_CheckedChanged({$install.Enabled=$accept.Checked;$offline.Enabled=$accept.Checked})
$install.Add_Click({$script:chosen='install';$script:suite=$folder.Text;$script:reports=$report.Checked;$form.Close()})
$offline.Add_Click({$d=New-Object System.Windows.Forms.FolderBrowserDialog;$d.Description='Escolha uma pasta vazia para levar o plugin à clínica';if($d.ShowDialog()-eq 'OK'){$script:offline=$d.SelectedPath;$script:suite=$folder.Text;$script:reports=$report.Checked;$script:chosen='offline';$form.Close()};$d.Dispose()})
$exit.Add_Click({$form.Close()})
[void]$form.ShowDialog()
$form.Dispose()
if(-not $script:chosen){exit 0}
try {
    $suitePath=[System.IO.Path]::GetFullPath($script:suite.Trim().Trim('"'))
    if($suitePath.TrimEnd('\') -eq [System.IO.Path]::GetPathRoot($suitePath).TrimEnd('\')){throw 'Escolha uma pasta dentro do disco, não a raiz.'}
    if($script:chosen -eq 'install') {
    $stamp=Join-Path $suitePath 'entrega.txt'
    if(Test-Path -LiteralPath $stamp -PathType Leaf) {
        $versionLine=Get-Content -LiteralPath $stamp | Where-Object {$_ -match '^VERSAO='} | Select-Object -First 1
        if(-not $versionLine -or [version]($versionLine.Split('=')[1].Trim()) -lt [version]'8.14') {throw 'Atualize a Local Suite existente para 8.14 pelo instalador da base e abra este START HERE novamente.'}
    } elseif(Test-Path -LiteralPath $suitePath) {
        $owned=(Test-Path -LiteralPath (Join-Path $suitePath '.lung-bootstrap')) -or (Test-Path -LiteralPath (Join-Path $suitePath '_instalacao\_motor_comecou.txt'))
        if(-not $owned -and @(Get-ChildItem -LiteralPath $suitePath -Force).Count -gt 0) {throw 'Escolha uma pasta vazia para a nova base ou uma Local Suite 8.14 já instalada.'}
    }
    }
    Write-Host 'LUNG RT — preparo local' -ForegroundColor Cyan
    Write-Host '1. Conferindo a base e o Python existente...'
    $python=Join-Path $suitePath 'python\python.exe'
    if(-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $pyTarget=if($script:chosen -eq 'offline'){Join-Path $env:TEMP ('lung-prepare-python-'+[guid]::NewGuid().ToString('N'))}else{Join-Path $suitePath 'python'}
        [void](New-Item -ItemType Directory -Path $pyTarget -Force)
        if($script:chosen -ne 'offline'){Set-Content -LiteralPath (Join-Path $suitePath '.lung-bootstrap') -Value 'LUNG RT portable runtime preparation' -Encoding ASCII}
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
    $runArgs=@('-I','-B',(Join-Path $base 'install.py'),'--suite-root',$suitePath,'--accept-terms')
    if($script:reports){$runArgs+='--reports'}
    if($script:chosen -eq 'offline'){$runArgs+=@('--offline',$script:offline)}
    Write-Host '3. Conferindo código, recursos e destino. Acompanhe o progresso abaixo...'
    & $python @runArgs
    if($LASTEXITCODE -ne 0){throw 'O preparo parou. Leia o motivo acima; os dados existentes foram preservados.'}
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
    Write-Host ('Não foi possível concluir: '+$_.Exception.Message) -ForegroundColor Yellow
    Write-Host 'Rede bloqueada? Prepare o pacote em outra máquina e use Configurações > Plugin LUNG RT > pasta offline.'
    [void](Read-Host 'Pressione Enter para fechar')
    exit 1
}
[void](Read-Host 'Pressione Enter para fechar')
