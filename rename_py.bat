@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: rename_py.bat
::
:: Usage:
::   rename_py.bat          -- renames all .py files to .txt
::   rename_py.bat undo     -- renames all .txt files back to .py
::
:: Runs recursively from whichever folder you place this script.
:: The script itself is skipped automatically.
:: ============================================================

if /i "%~1"=="undo" goto :undo

:: ── FORWARD: .py -> .txt ─────────────────────────────────────
echo Renaming .py to .txt...
set COUNT=0
for /r %%F in (*.py) do (
    ren "%%F" "%%~nF.txt"
    echo   %%F
    set /a COUNT+=1
)
echo.
echo Done. !COUNT! file(s) renamed.
goto :end


:: ── UNDO: .txt -> .py ────────────────────────────────────────
:undo
echo Renaming .txt back to .py...
set COUNT=0
for /r %%F in (*.txt) do (
    ren "%%F" "%%~nF.py"
    echo   %%F
    set /a COUNT+=1
)
echo.
echo Done. !COUNT! file(s) renamed.


:end
exit /b 0