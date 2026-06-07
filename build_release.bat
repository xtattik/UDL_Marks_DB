@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ============================================
echo   UDL Marks Database ^| Build Release
echo  ============================================
echo.

:: ── Configuration ────────────────────────────────────────────────────────────
set PY_VERSION=3.12.10
set PY_SHORT=312
set DIST_NAME=UDL-Marks-DB
set DIST_DIR=dist\%DIST_NAME%
set ZIP_OUT=%DIST_NAME%-release.zip

:: ── Clean previous build ─────────────────────────────────────────────────────
if exist dist      rmdir /s /q dist
if exist %ZIP_OUT% del /q %ZIP_OUT%
mkdir "%DIST_DIR%\templates"

echo [1/7] Downloading Python %PY_VERSION% embeddable package...
powershell -NoProfile -Command ^
  "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-embed-amd64.zip' -OutFile 'dist\python-embed.zip' -UseBasicParsing"
if errorlevel 1 (
  echo.
  echo  ERROR: Download failed. Check your internet connection and try again.
  pause & exit /b 1
)

echo [2/7] Extracting Python...
powershell -NoProfile -Command ^
  "Expand-Archive -Path 'dist\python-embed.zip' -DestinationPath '%DIST_DIR%\python' -Force"

:: Enable site-packages so pip and installed libs are importable
powershell -NoProfile -Command ^
  "(Get-Content '%DIST_DIR%\python\python%PY_SHORT%._pth') -replace '#import site','import site' | Set-Content '%DIST_DIR%\python\python%PY_SHORT%._pth'"

echo [3/7] Bootstrapping pip...
powershell -NoProfile -Command ^
  "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'dist\get-pip.py' -UseBasicParsing"
"%DIST_DIR%\python\python.exe" dist\get-pip.py --no-warn-script-location -q
if errorlevel 1 (
  echo  ERROR: pip installation failed.
  pause & exit /b 1
)

echo [4/7] Installing Flask...
"%DIST_DIR%\python\python.exe" -m pip install flask --no-warn-script-location -q
if errorlevel 1 (
  echo  ERROR: Flask installation failed.
  pause & exit /b 1
)

echo [5/7] Copying application files...
copy /y app.py          "%DIST_DIR%\"          > nul
copy /y requirements.txt "%DIST_DIR%\"         > nul
xcopy /e /i /q /y templates "%DIST_DIR%\templates" > nul

echo [6/7] Creating clean database...
"%DIST_DIR%\python\python.exe" make_clean_db.py "%DIST_DIR%\udl_marks_db.sqlite"
if errorlevel 1 (
  echo  ERROR: Database creation failed.
  pause & exit /b 1
)

echo [7/7] Writing launcher, quickstart, and packaging...

:: ── Launcher (written into the dist folder) ───────────────────────────────────
(
echo @echo off
echo cd /d "%%~dp0"
echo title UDL Marks Database
echo echo.
echo echo   UDL Marks Database is starting...
echo echo   Your browser will open automatically.
echo echo   Keep this window open while using the app.
echo echo   Close it to shut down the server.
echo echo.
echo start "" /b cmd /c "timeout /t 2 ^>nul ^&^& start http://127.0.0.1:5000"
echo python\python.exe app.py
echo pause
) > "%DIST_DIR%\Start UDL Marks DB.bat"

:: ── Quickstart guide ──────────────────────────────────────────────────────────
(
echo UDL Marks Database — Quick Start Guide
echo =======================================
echo.
echo TO START THE APP
echo ----------------
echo Double-click "Start UDL Marks DB.bat"
echo Your browser will open to http://127.0.0.1:5000 automatically.
echo Keep the command window open — close it to stop the server.
echo.
echo FIRST-TIME SETUP ^(do these in order^)
echo --------------------------------------
echo 1. Settings ^> Subjects
echo    Add your subjects: Science, Mathematics, English, PDHPE, etc.
echo.
echo 2. Settings ^> Classes
echo    Add your class groups. Use the class code field for groups
echo    within the same year and subject ^(e.g. 9.1, 9.2, 9T^).
echo.
echo 3. Settings ^> Students ^> Import from CSV
echo    Load your student roll. CSV must have these columns:
echo      student_id, first_name, last_name, year_group
echo    year_group should match exactly, e.g. "Year 9"
echo.
echo 4. Settings ^> Classes ^> Roster
echo    For each class, click Roster and add the enrolled students.
echo.
echo 5. Settings ^> Outcomes
echo    Outcomes are created automatically when you import marks.
echo    Use this page to assign each outcome a subject and stage
echo    ^(required for class heatmaps and cross-curricular tracking^).
echo.
echo ENTERING MARKS
echo --------------
echo - New Entry:   one student, any outcomes, scored individually
echo - Bulk Entry:  whole class in a grid ^(students x outcomes^)
echo - Import:      upload a CSV exported from the rubric marking tool
echo.
echo YOUR DATA
echo ---------
echo All data is stored locally in udl_marks_db.sqlite ^(this folder^).
echo Back this file up regularly — it is the entire database.
echo Copying the whole folder is sufficient for a full backup.
echo.
echo Need help? Contact your IT coordinator or the app developer.
) > "%DIST_DIR%\QUICKSTART.txt"

:: ── Package into ZIP ──────────────────────────────────────────────────────────
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%DIST_DIR%' -DestinationPath '%ZIP_OUT%' -Force"

:: ── Cleanup temp files ────────────────────────────────────────────────────────
del /q dist\python-embed.zip 2>nul
del /q dist\get-pip.py       2>nul

echo.
echo  ============================================
echo   Done!
echo   Distributable: %ZIP_OUT%
echo   ~20 MB — share this ZIP with staff.
echo  ============================================
echo.
pause
