@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   ESP32 串口助手 - 一键打包脚本 (优化版)
echo ============================================
echo.

where pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] 正在安装 PyInstaller ...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [!] PyInstaller 安装失败，请检查 Python 环境
        pause
        exit /b 1
    )
)

echo [*] 正在查找 customtkinter 路径 ...
for /f "delims=" %%i in ('python -c "import customtkinter, os; print(os.path.dirname(customtkinter.__file__))"') do set CTK_PATH=%%i

if "%CTK_PATH%"=="" (
    echo [!] 找不到 customtkinter，请先运行: pip install customtkinter
    pause
    exit /b 1
)

echo [*] customtkinter 路径: %CTK_PATH%

:: 检查 UPX
set UPX_OPT=
if exist "upx\upx.exe" (
    echo [*] 检测到 UPX，将启用压缩
    set UPX_OPT=--upx-dir upx
) else (
    echo [*] 未检测到 UPX，跳过压缩 (可选: 下载 upx.exe 放入 upx\ 目录进一步压缩)
)

echo [*] 开始打包 ...
echo.

pyinstaller --noconfirm --onefile --windowed ^
    --name "ESP32串口助手" ^
    --add-data "%CTK_PATH%;customtkinter" ^
    --hidden-import "serial" ^
    --hidden-import "serial.tools" ^
    --hidden-import "serial.tools.list_ports" ^
    --hidden-import "serial.tools.list_ports_common" ^
    --hidden-import "serial.tools.list_ports_windows" ^
    --hidden-import "customtkinter" ^
    --hidden-import "darkdetect" ^
    --hidden-import "packaging" ^
    --hidden-import "packaging.version" ^
    --hidden-import "packaging.requirements" ^
    --exclude-module "PIL" ^
    --exclude-module "Pillow" ^
    --exclude-module "numpy" ^
    --exclude-module "pandas" ^
    --exclude-module "matplotlib" ^
    --exclude-module "scipy" ^
    --exclude-module "cv2" ^
    --exclude-module "PyQt5" ^
    --exclude-module "PyQt6" ^
    --exclude-module "PySide2" ^
    --exclude-module "PySide6" ^
    --exclude-module "wx" ^
    --exclude-module "unittest" ^
    --exclude-module "pytest" ^
    --exclude-module "doctest" ^
    --exclude-module "pydoc" ^
    --exclude-module "xmlrpc" ^
    --exclude-module "multiprocessing" ^
    --exclude-module "asyncio" ^
    --exclude-module "concurrent" ^
    --exclude-module "email" ^
    --exclude-module "html" ^
    --exclude-module "http" ^
    --exclude-module "urllib" ^
    --exclude-module "xml" ^
    --exclude-module "zipimport" ^
    --exclude-module "lib2to3" ^
    --exclude-module "pdb" ^
    --exclude-module "curses" ^
    --exclude-module "distutils" ^
    --exclude-module "setuptools" ^
    --exclude-module "pkg_resources" ^
    --exclude-module "_ssl" ^
    --exclude-module "ssl" ^
    --exclude-module "hashlib" ^
    --exclude-module "ftplib" ^
    --exclude-module "imaplib" ^
    --exclude-module "smtplib" ^
    --exclude-module "sqlite3" ^
    --exclude-module "decimal" ^
    --exclude-module "fractions" ^
    --exclude-module "statistics" ^
    --exclude-module "csv" ^
    --exclude-module "difflib" ^
    --exclude-module "textwrap" ^
    --exclude-module "pprint" ^
    --exclude-module "argparse" ^
    --exclude-module "optparse" ^
    --exclude-module "gettext" ^
    --exclude-module "locale" ^
    --exclude-module "calendar" ^
    --exclude-module "turtle" ^
    --exclude-module "turtledemo" ^
    --exclude-module "tkinter.tix" ^
    %UPX_OPT% ^
    serial_assistant.py

echo.
if %errorlevel% equ 0 (
    for %%A in ("dist\ESP32串口助手.exe") do set FILE_SIZE=%%~zA
    set /a FILE_SIZE_MB=%FILE_SIZE% / 1048576
    echo ============================================
    echo   打包成功！
    echo   输出文件: dist\ESP32串口助手.exe
    echo   文件大小: 约 %FILE_SIZE_MB% MB
    echo ============================================
    echo.
    echo 按任意键打开输出目录 ...
    pause >nul
    explorer dist
) else (
    echo [!] 打包失败，请检查上方错误信息
    pause
)
