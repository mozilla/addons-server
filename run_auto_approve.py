import subprocess
import time

def approve_addons():
    while True:
        subprocess.call(["python", "manage.py", "auto_approve"])
        time.sleep(10)

if __name__ == "__main__":
    approve_addons()