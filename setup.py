#!/usr/bin/env python3
"""Setup script for Price Tracker application."""

import os
import subprocess
import sys
from pathlib import Path

def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e}")
        print(f"Error output: {e.stderr}")
        return False

def main():
    """Main setup function."""
    print("🚀 Setting up Price Tracker...")
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ is required")
        sys.exit(1)
    
    print(f"✅ Python {sys.version.split()[0]} detected")
    
    # Create virtual environment if it doesn't exist
    venv_path = Path(".venv")
    if not venv_path.exists():
        if not run_command("python -m venv .venv", "Creating virtual environment"):
            sys.exit(1)
    
    # Determine activation script based on OS
    if os.name == 'nt':  # Windows
        activate_script = ".venv\\Scripts\\activate"
        pip_cmd = ".venv\\Scripts\\pip"
    else:  # Unix/Linux/Mac
        activate_script = ".venv/bin/activate"
        pip_cmd = ".venv/bin/pip"
    
    # Install requirements
    if not run_command(f"{pip_cmd} install --upgrade pip", "Upgrading pip"):
        sys.exit(1)
    
    if not run_command(f"{pip_cmd} install -r requirements.txt", "Installing dependencies"):
        sys.exit(1)
    
    # Create necessary directories
    directories = [
        "data",
        "logs", 
        "static/images",
        "static/css"
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"✅ Created directory: {directory}")
    
    # Create .env file if it doesn't exist
    env_file = Path(".env")
    if not env_file.exists():
        env_content = """EMAIL_ADDRESS=your_email@gmail.com
EMAIL_APP_PASSWORD=your_app_password
DATABASE_PATH=./data/products.db
LOG_LEVEL=INFO
ADMIN_EMAIL=your_email@gmail.com
PROXY_URL=
"""
        with open(env_file, 'w') as f:
            f.write(env_content)
        print("✅ Created .env file (please update with your email settings)")
    else:
        print("✅ .env file already exists")
    
    print("\n🎉 Setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Update .env file with your email credentials")
    print("2. Run: streamlit run app.py")
    print("3. Open your browser to http://localhost:8501")
    print("\n💡 For Gmail, use App Passwords instead of your regular password")

if __name__ == "__main__":
    main()

