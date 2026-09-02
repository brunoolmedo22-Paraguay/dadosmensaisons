@echo off
setlocal
title Dados Mensais ONS v10
cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv_v10"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Preparando o ambiente da versao 10...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 goto :erro
    "%PYTHON_EXE%" -m pip install --upgrade pip
    if errorlevel 1 goto :erro
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 goto :erro
)

"%PYTHON_EXE%" -m streamlit run app.py
if errorlevel 1 goto :erro
exit /b 0

:erro
echo.
echo Nao foi possivel iniciar a aplicacao.
pause
exit /b 1
