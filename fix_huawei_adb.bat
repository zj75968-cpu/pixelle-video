@echo off
echo Fixing Huawei ADB DeviceInterfaceGUIDs ...
reg add "HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_12D1&PID_107E&MI_02\6&48EBBBA&3&0002\Device Parameters" /v DeviceInterfaceGUIDs /t REG_MULTI_SZ /d "{F72FE0D4-CBCB-407d-8814-9ED673D0DD6B}" /f
if %ERRORLEVEL% EQU 0 (
    echo GUID OK
) else (
    echo FAILED - run as admin
)
adb kill-server
timeout /t 2 /nobreak >nul
adb devices -l
pause
