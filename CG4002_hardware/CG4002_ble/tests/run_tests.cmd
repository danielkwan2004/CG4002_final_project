@echo off
setlocal
call "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
set "BLE_TEST_OUTPUT=%TEMP%\cg4002-ble-tests"
if not exist "%BLE_TEST_OUTPUT%" mkdir "%BLE_TEST_OUTPUT%"
pushd "%BLE_TEST_OUTPUT%"
cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS "%~dp0ble_queue_test.cpp" /Fe:ble_queue_test.exe
if errorlevel 1 (popd & exit /b 1)
ble_queue_test.exe
if errorlevel 1 (popd & exit /b 1)
cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS /I"%~dp0stubs" "%~dp0pipeline_test.cpp" "%~dp0..\ICM42686P.cpp" "%~dp0..\Calibration.cpp" "%~dp0..\LowPassFilter.cpp" "%~dp0..\MoveDetector.cpp" "%~dp0..\Haptics.cpp" /Fe:pipeline_test.exe
if errorlevel 1 (popd & exit /b 1)
pipeline_test.exe
if errorlevel 1 (popd & exit /b 1)
pipeline_test.exe calibration-failure
if errorlevel 1 (popd & exit /b 1)
set "BLE_PACKET_FIXTURE=%BLE_TEST_OUTPUT%\ble_packet.bin"
if "%~1"=="" (set "BLE_TEST_PYTHON=python") else (set "BLE_TEST_PYTHON=%~1")
"%BLE_TEST_PYTHON%" -B -m unittest discover -s "%~dp0." -v
set "BLE_TEST_RESULT=%errorlevel%"
popd
exit /b %BLE_TEST_RESULT%
