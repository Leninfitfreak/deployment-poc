@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ARGOCD_LOCAL_PORT=18085"
set "ARGOCD_LOG=%RUNNER_TEMP%\argocd-port-forward.log"

if exist "%ARGOCD_LOG%" del /f /q "%ARGOCD_LOG%"
start "argocd-port-forward" /MIN cmd /c call scripts\run-argocd-port-forward.cmd "%ARGOCD_LOG%"

set /a ATTEMPTS=0
:wait_for_argocd
curl.exe -k -s https://127.0.0.1:%ARGOCD_LOCAL_PORT%/api/version >NUL 2>&1
if not errorlevel 1 (
  echo ArgoCD port-forward is ready on %ARGOCD_LOCAL_PORT%
  exit /b 0
)
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ 30 goto port_forward_failed
timeout /t 2 /nobreak >NUL
goto wait_for_argocd

:port_forward_failed
if exist "%ARGOCD_LOG%" type "%ARGOCD_LOG%"
echo Timed out waiting for ArgoCD port-forward on port %ARGOCD_LOCAL_PORT%
exit /b 1
