#!/usr/bin/env python3

import os
import subprocess
import sys
import time


env = os.environ.copy()

env['DJANGO_SETTINGS_MODULE'] = 'olympia'


def worker_healthcheck():
    subprocess.run(
        ['celery', '-A', 'olympia.amo.celery', 'status'],
        env=env,
        stdout=subprocess.DEVNULL,
    )


def web_healthcheck():
    subprocess.run(
        [
            'curl',
            '--fail',
            '--show-error',
            '--include',
            '--location',
            '--silent',
            'http://127.0.0.1:8002/__version__',
        ],
        stdout=subprocess.DEVNULL,
    )


TIME = time.time()
TIMEOUT = 60
SLEEP = 1

while time.time() - TIME < TIMEOUT:
    try:
        worker_healthcheck()
        web_healthcheck()
        print('OK')
        sys.exit(0)
    except Exception as e:
        print(f'Error: {e}')
        time.sleep(SLEEP)
        SLEEP *= 2
