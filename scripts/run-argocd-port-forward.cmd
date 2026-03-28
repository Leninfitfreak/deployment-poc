@echo off
setlocal EnableExtensions
set "ARGOCD_LOG=%~1"
if "%ARGOCD_LOG%"=="" set "ARGOCD_LOG=%TEMP%\argocd-port-forward.log"
kubectl port-forward -n argocd svc/argocd-server 18085:443 >> "%ARGOCD_LOG%" 2>&1
