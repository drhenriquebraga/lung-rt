@echo off
setlocal
set "LUNG_RT_INSTALL_LOG_DIR=%LOCALAPPDATA%\RadioterapiaAI\LUNG RT\Logs"
if not defined LOCALAPPDATA set "LUNG_RT_INSTALL_LOG_DIR=%TEMP%"
if not exist "%LUNG_RT_INSTALL_LOG_DIR%\." mkdir "%LUNG_RT_INSTALL_LOG_DIR%" >nul 2>&1
if not exist "%LUNG_RT_INSTALL_LOG_DIR%\." set "LUNG_RT_INSTALL_LOG_DIR=%TEMP%"
set "launchLog=%LUNG_RT_INSTALL_LOG_DIR%\LUNG_RT_START_HERE.log"
if not exist "%~dp0INSTALL.ps1" goto :incomplete

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0INSTALL.ps1"
set "result=%ERRORLEVEL%"
if "%result%"=="0" exit /b 0
echo.
echo A instalacao parou. Codigo de saida: %result%
echo [%DATE% %TIME%] INSTALL_EXIT %result%>>"%launchLog%"
goto :failed

:incomplete
set "result=2"
echo PACKAGE_INCOMPLETE: INSTALL.ps1 nao encontrado ao lado do START HERE.
echo No Explorador, clique com o botao direito no ZIP e escolha Extrair Tudo.
echo Abra a pasta extraida e execute START_HERE.cmd para preparar o pacote offline.
echo [%DATE% %TIME%] PACKAGE_INCOMPLETE: INSTALL.ps1 ausente.>>"%launchLog%"

:failed
echo Logs: "%LUNG_RT_INSTALL_LOG_DIR%"
echo Pressione uma tecla para fechar.
pause >nul
exit /b %result%
