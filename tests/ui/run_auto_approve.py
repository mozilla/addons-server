import subprocess
import time


# Script for running the auto approve command every 10 seconds for 5 minutes.
def approve_addons():
    start_time = time.time()
    # run for 5 minutes max
    while time.time() != start_time + 300:
        subprocess.call(['python', 'manage.py', 'auto_approve'])
        time.sleep(10)


if __name__ == '__main__':
    approve_addons()
