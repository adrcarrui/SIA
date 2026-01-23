import subprocess

cmd = r'cd /d C:\Users\adrian\SIA\itc-gui && call .\venv\Scripts\activate.bat && python wsgi.py'
# /k: deja la consola abierta después de ejecutar
subprocess.Popen(["cmd.exe", "/k", cmd], creationflags=subprocess.CREATE_NEW_CONSOLE)
