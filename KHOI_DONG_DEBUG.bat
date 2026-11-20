@echo off
setlocal
chcp 65001 >nul
title VN Land Counsel - Clean Pipeline Debug
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_local.ps1" -ModelProfile answer_8b -PlannerVariant lora_8b_sft_3000 -AppMode terminal -Port 8080 -ContextSize 20000 -PipelineDebug -DebugMaxChars 200000

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo Khoi dong debug that bai voi ma loi %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
