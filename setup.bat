@echo off
REM Financial Document Analyzer - Quick Setup Script (Windows)
REM Law Firm Edition - Version 2.0

echo ==============================================
echo Financial Document Analyzer - Setup
echo Law Firm Edition
echo ==============================================
echo.

REM Check Python version
echo Checking Python version...
python --version
if errorlevel 1 (
    echo ERROR: Python is not installed
    echo Please install Python 3.10 or higher from python.org
    pause
    exit /b 1
)

echo OK: Python is installed
echo.

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo OK: Dependencies installed
echo.

REM Check if .env file exists
if not exist .env (
    echo Creating .env file...
    (
        echo # Google Gemini AI API Key
        echo # Get from: https://makersuite.google.com/app/apikey
        echo GEMINI_API_KEY=your_gemini_api_key_here
        echo.
        echo # Gmail Account for Email Processing
        echo # Use App Password, not regular password
        echo # Enable 2FA first, then: Google Account -^> Security -^> App Passwords
        echo EMAIL_ADDRESS=yourfirm@gmail.com
        echo EMAIL_PASSWORD=your_gmail_app_password_here
    ) > .env
    echo OK: Created .env file
    echo.
    echo WARNING: Edit the .env file and add your API keys!
    echo.
) else (
    echo WARNING: .env file already exists - not overwriting
    echo.
)

REM Create necessary directories
echo Creating directories...
if not exist incoming_pdfs mkdir incoming_pdfs
echo OK: Directories created
echo.

echo ==============================================
echo Setup Complete!
echo ==============================================
echo.
echo Next Steps:
echo.
echo 1. Edit the .env file and add your API keys:
echo    - GEMINI_API_KEY (from https://makersuite.google.com/app/apikey)
echo    - EMAIL_ADDRESS (your Gmail address)
echo    - EMAIL_PASSWORD (Gmail App Password)
echo.
echo 2. Start the server:
echo    uvicorn main:app --reload
echo.
echo 3. Open your browser:
echo    http://localhost:8000
echo.
echo 4. Upload your first document!
echo.
echo Documentation:
echo    - Quick Start: README.md
echo    - Complete Guide: See LAW-FIRM-SETUP-GUIDE.md (in parent folder)
echo    - Technical Details: See MODIFICATION-SUMMARY.md (in parent folder)
echo.
echo ==============================================
echo.
pause
