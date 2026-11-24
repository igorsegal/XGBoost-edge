@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d D:\AHexaTrader\XGBoost-edge-git\registry
set GPP=D:\AHexaTrader\0COMPILER\bin\g++.exe
set PY=D:\Python314\python.exe
if not exist "%GPP%" ( echo NO COMPILER %GPP% & pause & exit /b 1 )
if not exist "%PY%" ( echo NO PYTHON %PY% & pause & exit /b 1 )
echo [1/5] compile tester...
"%GPP%" -O2 -std=c++17 -o tester\tester.exe tester\tester.cpp
if errorlevel 1 ( echo COMPILE FAILED & pause & exit /b 1 )
echo [2/5] validate registry...
"%PY%" validate_registry.py
if errorlevel 1 ( echo REGISTRY INVALID & pause & exit /b 1 )
echo [3/5] check indicators against independent Python...
"%PY%" tests\xcheck_indicators.py tester\tester.exe D:\AHexaTrader\1DataFiles\raw\EURUSD\EURUSD_H1.bin
if errorlevel 1 ( echo INDICATOR CHECK FAILED & pause & exit /b 1 )
"%PY%" tests\xcheck_indicators2.py tester\tester.exe D:\AHexaTrader\1DataFiles\raw\EURUSD\EURUSD_H1.bin
if errorlevel 1 ( echo INDICATOR CHECK 2 FAILED & pause & exit /b 1 )
echo [4/5] run all configs...
for %%f in (configs\*.json) do ( echo ===== %%f & tester\tester.exe "%%f" --selftest )
echo [5/5] record results into registry...
"%PY%" record_results.py
echo.
echo DONE
pause
