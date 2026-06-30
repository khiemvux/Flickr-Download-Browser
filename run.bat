@echo off
title Flickr Download Browser
setlocal

cd /d "%~dp0"

REM ---------------------------------------------------------------
REM  Detect a working Python 3 interpreter
REM  Priority: py launcher > python3 > python
REM ---------------------------------------------------------------
set "PYTHON_EXE="

REM --- Try the Windows py launcher first (always on PATH if any Python is installed) ---
where py >nul 2>&1
if not errorlevel 1 (
    py --version >nul 2>&1
    if not errorlevel 1 (
        py -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_EXE=py"
        )
    )
)

REM --- Fallback 1: python3 ---
if "%PYTHON_EXE%"=="" (
    where python3 >nul 2>&1
    if not errorlevel 1 (
        python3 --version >nul 2>&1
        if not errorlevel 1 (
            python3 -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_EXE=python3"
            )
        )
    )
)

REM --- Fallback 2: python ---
if "%PYTHON_EXE%"=="" (
    where python >nul 2>&1
    if not errorlevel 1 (
        python --version >nul 2>&1
        if not errorlevel 1 (
            python -c "import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_EXE=python"
            )
        )
    )
)

REM --- All detection attempts failed ---
if "%PYTHON_EXE%"=="" (
    echo No working Python 3 interpreter was found.
    echo.
    echo Possible solutions:
    echo   1. Install Python 3 from https://python.org
    echo      ^(check "Add Python to PATH" during installation^)
    echo   2. If Python is already installed, try running the script
    echo      from a new Command Prompt window
    echo   3. Make sure "App Execution Aliases" for Python are enabled
    echo      in Windows Settings ^> Apps ^> App execution aliases
    echo.
    echo Detected Python candidates:
    where py      2>nul || echo   - py launcher:   NOT FOUND
    where python3 2>nul || echo   - python3:        NOT FOUND
    where python  2>nul || echo   - python:         NOT FOUND
    pause
    exit /b 1
)

echo Using Python interpreter: %PYTHON_EXE%

REM Create virtual environment if it does not exist
if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    %PYTHON_EXE% -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created.
)

REM Install/update dependencies
echo Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

REM Launch the application
echo Starting Flickr Download Browser...
.venv\Scripts\python.exe flickr_downloader_app.py
if errorlevel 1 (
    echo Application exited with an error.
    pause
    exit /b 1
)

endlocal
exit /b 0
