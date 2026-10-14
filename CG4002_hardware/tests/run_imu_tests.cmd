@echo off
setlocal
call "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
set "IMU_TEST_OUTPUT=%TEMP%\cg4002-imu-tests"
if not exist "%IMU_TEST_OUTPUT%" mkdir "%IMU_TEST_OUTPUT%"
pushd "%IMU_TEST_OUTPUT%"
cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS /I"%~dp0stubs" "%~dp0imu_pipeline_test.cpp" "%~dp0..\ICM42686P.cpp" "%~dp0..\LowPassFilter.cpp" "%~dp0..\MoveDetector.cpp" "%~dp0..\Calibration.cpp" "%~dp0..\CaptureDiagnostics.cpp" /Fe:imu_pipeline_test.exe
if errorlevel 1 (popd & exit /b 1)
imu_pipeline_test.exe
if errorlevel 1 (popd & exit /b 1)
imu_pipeline_test.exe calibration-failure
set "IMU_TEST_RESULT=%errorlevel%"
popd
exit /b %IMU_TEST_RESULT%
