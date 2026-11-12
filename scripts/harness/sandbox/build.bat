@echo off
REM Build S2SSandbox.dll: the profile redirection a headless test instance is injected with before SFSE.
REM Not an SFSE plugin and never installed into the game. Needs Visual Studio (any edition) with the
REM "Desktop development with C++" workload; vswhere finds it. The DLL goes to bin\ (the guard and Git skip bin\ and obj\).
REM See scripts/harness/README.md

setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
    echo [build] ERROR: vswhere.exe not found; install Visual Studio with the C++ workload
    exit /b 1
)
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSDIR=%%i"
if not defined VSDIR (
    echo [build] ERROR: no Visual Studio with the x64 C++ tools found
    exit /b 1
)
call "%VSDIR%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1

cd /d "%~dp0"
if not exist obj mkdir obj
if not exist bin mkdir bin
cl /nologo /c /EHsc /std:c++17 /O2 /MD /W3 /DNDEBUG sandbox.cpp /Fo:obj\
if errorlevel 1 (
    echo [build] ERROR: compilation failed
    exit /b 1
)
link /nologo /DLL /OUT:bin\S2SSandbox.dll obj\sandbox.obj kernel32.lib shell32.lib ole32.lib uuid.lib
if errorlevel 1 (
    echo [build] ERROR: link failed
    exit /b 1
)
echo [build] OK -^> %~dp0bin\S2SSandbox.dll
