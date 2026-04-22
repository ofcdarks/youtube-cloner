import subprocess
import os

os.chdir(r"c:\Users\DigiAi\Desktop\FINAL PIPELINE\cloner")

files = [
    "routes/student_routes.py",
    "routes/api_routes.py", 
    "protocols/ai_client.py",
    "protocols/viral_engine.py",
    "tools/fix_student_prompt.py"
]

print("=== GIT ADD ===")
r = subprocess.run(["git", "add"] + files, capture_output=True, text=True)
print(r.stdout or "(ok)")
if r.stderr: print(r.stderr)

print("\n=== GIT COMMIT ===")
r = subprocess.run(["git", "commit", "-m", "fix: roteiro aluno corrido + titulos 50-80 chars"], capture_output=True, text=True)
print(r.stdout or "(ok)")
if r.stderr: print(r.stderr)

print("\n=== GIT PUSH ===")
r = subprocess.run(["git", "push"], capture_output=True, text=True, timeout=60)
print(r.stdout or "(ok)")
if r.stderr: print(r.stderr)

print("\n=== DONE ===")
