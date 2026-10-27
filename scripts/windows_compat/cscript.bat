@echo off
setlocal
set PYTHONHOME=
set PYTHONPATH=
"%OBSIDIAN_BUILD_PYTHON%" "%~dp0patch_ise_wrapper.py" %*
if errorlevel 1 exit /b 1
"%SystemRoot%\System32\cscript.exe" %*
exit /b %errorlevel%
