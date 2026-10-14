@echo off
setlocal
rem Uses the existing Microsoft C++ Build Tools; installs nothing.
call "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1
set "TX_TEST_OUTPUT=%TEMP%\cg4002-txqueue-tests"
if not exist "%TX_TEST_OUTPUT%" mkdir "%TX_TEST_OUTPUT%"
cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS "%~dp0tx_queue_test.cpp" /Fe:"%TX_TEST_OUTPUT%\tx_queue_test.exe" /Fo:"%TX_TEST_OUTPUT%\tx_queue_test.obj"
if errorlevel 1 exit /b 1
"%TX_TEST_OUTPUT%\tx_queue_test.exe"
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS /I"%~dp0stubs" /c "%~dp0..\CaptureDiagnostics.cpp" /Fo:"%TX_TEST_OUTPUT%\CaptureDiagnostics.obj"
if errorlevel 1 exit /b 1
cl /nologo /std:c++17 /EHsc /W4 /D_CRT_SECURE_NO_WARNINGS /I"%~dp0stubs" "%~dp0capture_queue_test.cpp" "%TX_TEST_OUTPUT%\CaptureDiagnostics.obj" /Fe:"%TX_TEST_OUTPUT%\capture_queue_test.exe" /Fo:"%TX_TEST_OUTPUT%\capture_queue_test.obj"
if errorlevel 1 exit /b 1
"%TX_TEST_OUTPUT%\capture_queue_test.exe"
exit /b %errorlevel%
