@echo off
chcp 65001 > NUL
cd /d "%~dp0"
title Delivery Optimizer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launcher.ps1"
if errorlevel 1 (
    echo.
    echo L'application n'a pas pu demarrer. Lisez le message ci-dessus ^(details dans le dossier "logs"^).
    pause
)
