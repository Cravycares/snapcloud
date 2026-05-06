"""
SnapCloud — local runner
========================
From the snapcloud/ folder, run:

    python run.py

Then open:  http://localhost:5000

Demo logins:
  creator@demo.com  / demo1234
  consumer@demo.com / demo1234
"""
import subprocess, sys, os

print("Installing Flask (if needed)…")
subprocess.check_call(
    [sys.executable, "-m", "pip", "install", "flask", "flask-cors", "--quiet"],
    stdout=subprocess.DEVNULL
)

print("Starting SnapCloud…")
print()
print("  Open this URL → http://localhost:5000")
print()
print("  Creator login : creator@demo.com  / demo1234")
print("  Consumer login: consumer@demo.com / demo1234")
print()
print("  Press Ctrl+C to stop.")
print()

# Run app.py directly — handles init_db on __main__
os.execv(sys.executable, [sys.executable, os.path.join("backend", "app.py")])
