# deploy.py
import subprocess
import sys
import os

def run_command(command, description):
    """Run shell command with error handling"""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e.stderr}")
        return False

def deploy():
    """Deploy to GitHub Pages"""
    # Check if git repo exists
    if not os.path.exists('.git'):
        print("❌ Not a git repository. Initialize first with: git init")
        sys.exit(1)
    
    # Generate site
    if not run_command("python generate_site.py", "Generating site"):
        sys.exit(1)
    
    # Deploy to GitHub
    commands = [
        ("git add .", "Adding files"),
        ("git commit -m 'Update CivicPulse site'", "Committing changes"),
        ("git push origin main", "Pushing to GitHub")
    ]
    
    for command, description in commands:
        if not run_command(command, description):
            sys.exit(1)
    
    print("🚀 Deployment complete!")
    print("📱 Your site will be live at: https://USERNAME.github.io/civicpulse")

if __name__ == "__main__":
    deploy()