#!/bin/bash

# Financial Document Analyzer - Quick Setup Script
# Law Firm Edition - Version 2.0

echo "=============================================="
echo "Financial Document Analyzer - Setup"
echo "Law Firm Edition"
echo "=============================================="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version

if [ $? -ne 0 ]; then
    echo "❌ Error: Python 3 is not installed"
    echo "Please install Python 3.10 or higher"
    exit 1
fi

echo "✅ Python is installed"
echo ""

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Error: Failed to install dependencies"
    exit 1
fi

echo "✅ Dependencies installed"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cat > .env << 'EOF'
# Google Gemini AI API Key
# Get from: https://makersuite.google.com/app/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# Gmail Account for Email Processing
# Use App Password, not regular password
# Enable 2FA first, then: Google Account → Security → App Passwords
EMAIL_ADDRESS=yourfirm@gmail.com
EMAIL_PASSWORD=your_gmail_app_password_here
EOF
    echo "✅ Created .env file"
    echo ""
    echo "⚠️  IMPORTANT: Edit the .env file and add your API keys!"
    echo ""
else
    echo "⚠️  .env file already exists - not overwriting"
    echo ""
fi

# Create necessary directories
echo "Creating directories..."
mkdir -p incoming_pdfs
echo "✅ Directories created"
echo ""

echo "=============================================="
echo "Setup Complete!"
echo "=============================================="
echo ""
echo "Next Steps:"
echo ""
echo "1. Edit the .env file and add your API keys:"
echo "   - GEMINI_API_KEY (from https://makersuite.google.com/app/apikey)"
echo "   - EMAIL_ADDRESS (your Gmail address)"
echo "   - EMAIL_PASSWORD (Gmail App Password)"
echo ""
echo "2. Start the server:"
echo "   uvicorn main:app --reload"
echo ""
echo "3. Open your browser:"
echo "   http://localhost:8000"
echo ""
echo "4. Upload your first document!"
echo ""
echo "📚 Documentation:"
echo "   - Quick Start: README.md"
echo "   - Complete Guide: See LAW-FIRM-SETUP-GUIDE.md (in parent folder)"
echo "   - Technical Details: See MODIFICATION-SUMMARY.md (in parent folder)"
echo ""
echo "=============================================="
