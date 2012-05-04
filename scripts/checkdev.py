import requests
import json
import re
import os
import time

synced = False

os.system('growlnotify --message "Watching -dev"')

while not synced:
    r = requests.get('https://api.github.com/repos/mozilla/zamboni/commits/master')
    obj = json.loads(r.content)
    git_sha = obj['sha']

    r = requests.get('https://marketplace-dev.allizom.org/media/updater.output.txt')
    for line in r.content.split('\n'):
        match = re.search(r'commit ([0-9 a-f]+)', line)
        if match:
            dev_sha = match.group(1)

    if git_sha == dev_sha and not synced:
        synced = True
        msg = '-dev is up to date\n%s - %s' % (obj['commit']['author']['name'],
                           obj['commit']['message'])
        os.system('growlnotify --message "%s"' % msg)
    else:
        time.sleep(15)