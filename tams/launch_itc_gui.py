import subprocess

cmd = r'cd /d C:\Users\ITC SUPPORT\TAMS\itc-gui2_patched2\itc-gui2 && call .\venv\Scripts\activate.bat && python wsgi.py'
# /k: deja la consola abierta después de ejecutar
subprocess.Popen(["cmd.exe", "/k", cmd], creationflags=subprocess.CREATE_NEW_CONSOLE)
