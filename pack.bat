@echo off
IF NOT EXIST 7z.exe GOTO NO7Z
IF NOT EXIST "DropForge" mkdir "DropForge"
rem Prepare files
copy /y /v dist\*.exe "DropForge"
copy /y /v manual.txt "DropForge"
IF EXIST "DropForge.zip" (
    rem Add action
    set action=a
) ELSE (
    rem Update action
    set action=u
)
rem Pack and test
7z %action% "DropForge.zip" "DropForge/" -r
7z t "DropForge.zip" * -r
rem Cleanup
IF EXIST "DropForge" rmdir /s /q "DropForge"
GOTO EXIT
:NO7Z
echo No 7z.exe detected, skipping packaging!
GOTO EXIT
:EXIT
exit %errorlevel%
