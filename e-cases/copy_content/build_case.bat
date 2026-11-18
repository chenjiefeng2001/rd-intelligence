@echo off
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" >nul
set SDK=D:\dummy
set KIT=C:\Program Files (x86)\Windows Kits\10
set UCRT=10.0.26100.0
set RDH=D:\renderdoc_no_mcp\renderdoc\x64\Release
cd /d "%~dp0"
cl /nologo /EHsc /Zi /Od /WX- /Fe:triangle_baseline.exe /Fd:triangle_baseline.pdb triangle_app.cpp /I "%RDH%" /link d3d11.lib dxgi.lib d3dcompiler.lib user32.lib kernel32.lib
if errorlevel 1 exit /b 1
cl /nologo /EHsc /Zi /Od /WX- /Fe:triangle_defect.exe /Fd:triangle_defect.pdb triangle_app_defect.cpp /I "%RDH%" /link d3d11.lib dxgi.lib d3dcompiler.lib user32.lib kernel32.lib
if errorlevel 1 exit /b 1
cl /nologo /EHsc /Zi /Od /WX- /Fe:triangle_fixed.exe /Fd:triangle_fixed.pdb triangle_app_fixed.cpp /I "%RDH%" /link d3d11.lib dxgi.lib d3dcompiler.lib user32.lib kernel32.lib
exit /b %errorlevel%
