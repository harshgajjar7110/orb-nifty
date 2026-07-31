import os
import sys
from dotenv import load_dotenv

def main():
    load_dotenv()
    print("Starting OSSE Streamlit Dashboard...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Add src directory to path
    os.environ['PYTHONPATH'] = os.path.join(base_dir, 'src')
    
    # Check for venv python executable
    venv_python_win = os.path.join(base_dir, 'venv', 'Scripts', 'python.exe')
    venv_python_nix = os.path.join(base_dir, 'venv', 'bin', 'python')
    
    if os.path.exists(venv_python_win):
        python_exec = venv_python_win
    elif os.path.exists(venv_python_nix):
        python_exec = venv_python_nix
    else:
        python_exec = sys.executable
        
    print(f"Using Python executable: {python_exec}")
    
    import subprocess
    dashboard_path = os.path.join(base_dir, 'src', 'osse', 'dashboard', 'app.py')
    subprocess.run([python_exec, "-m", "streamlit", "run", dashboard_path])

if __name__ == "__main__":
    main()

