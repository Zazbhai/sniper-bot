@echo off
echo ===========================================
echo      Building FLIPKART SNIPER (Nuitka)
echo ===========================================

rem Use Python 3.10
set PYTHON=py -3.10

echo Cleaning old build...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo Building EXE...

%PYTHON% -m nuitka ^
  --standalone ^
  --follow-imports ^
  --enable-plugin=tk-inter ^
  --include-module=flask ^
  --include-package=jinja2 ^
  --include-package=werkzeug ^
  --include-package=pymongo ^
  --include-package=selenium ^
  --include-package=requests ^
  --include-data-file=utils/chromedriver.exe=chromedriver.exe ^
  --include-data-file=imap_config.json=imap_config.json ^
  --output-dir=dist ^
  utils/app.py

echo ===========================================
echo BUILD COMPLETE
echo EXE stored in: dist\app.dist\app.exe
echo imap_config.json is in: dist\app.dist\imap_config.json (editable)
echo ===========================================
pause
