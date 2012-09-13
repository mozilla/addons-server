import json
import requests
import os
import time


GH_URL = 'https://api.github.com/repos/mozilla/zamboni/commits/master'
DEV_URL = 'https://marketplace-dev.allizom.org/media/git-rev.txt'
messaged = False


def alert(msg):
    os.system('growlnotify --message "%s"' % msg)


alert('Watching -dev')


while True:
    r = requests.get(GH_URL)
    obj = json.loads(r.content)
    git_sha = obj['sha'][:7]

    r = requests.get(DEV_URL)
    dev_sha = r.content.strip()

    if git_sha == dev_sha:
        msg = '-dev is up to date\n%s - %s' % (obj['commit']['author']['name'],
                                               obj['commit']['message'])
        alert(msg)
        break
    else:
        if not messaged:
            alert('-dev is behind master\n%s...%s' % (git_sha, dev_sha))
            messaged = True
        time.sleep(15)
