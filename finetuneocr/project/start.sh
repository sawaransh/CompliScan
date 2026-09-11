#!/bin/bash
# CompliScan - Quick Start Script

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "  CompliScan - SIH 2026 Prototype"
echo "========================================"
echo ""

# Check prerequisites
check_command() {
    if ! command -v $1 &> /dev/null; then
        echo "❌ $1 is not installed. Please install $1 first."
        exit 1
    fi
    echo "✅ $1 found"
}

echo "Checking prerequisites..."
check_command python3
check_command node
check_command npm

echo ""
echo "Setting up backend..."
cd "$PROJECT_DIR/backend"

if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "Installing Python dependencies..."
pip install -q -r requirements.txt

echo ""
echo "Setting up frontend..."
cd "$PROJECT_DIR/frontend"

if [ ! -d "node_modules" ]; then
    echo "Installing Node dependencies..."
    npm install
fi

echo ""
echo "========================================"
echo "  Starting CompliScan..."
echo "========================================"
echo ""
echo "Backend will run on: http://localhost:8000"
echo "Frontend will run on: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

# Start backend in background
cd "$PROJECT_DIR/backend"
source venv/bin/activate
python -m app.main &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 3

# Start frontend
cd "$PROJECT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

# Trap Ctrl+C to kill both processes
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo ''; echo 'Servers stopped.'; exit 0" INT

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID