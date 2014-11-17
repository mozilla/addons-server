#!/usr/bin/env python
import os
import re
import time

towatch = []
includes = {}


def say(s):
    t = time.strftime('%X')
    print '[%s] %s' % (t, s)


def render_list(files):
    for f in files:
        os.system('lessc %s %s.css' % (f, f))
        if (f in includes):
            say('re-compiling %d dependencies' % len(includes[f]))
            render_list(includes[f])
    say('re-compiled %d files' % len(files))


def watch():
    say('watching %d files...' % len(towatch))
    before = set([(f, os.stat(f).st_mtime) for f in towatch])
    while 1:
        after = set([(f, os.stat(f).st_mtime) for f in towatch])
        changed = [f for (f, d) in before.difference(after)]
        if len(changed):
            render_list(changed)
        before = after
        time.sleep(.5)


for root, dirs, files in os.walk('./media'):
    less = filter(lambda x: re.search('\.less$', x), files)
    less = [(root + '/' + f) for f in less]
    for f in less:
        body = post_file = open(f, 'r').read()
        m = re.search('@import \'([a-zA-Z0-9_-]+)\';', body)
        if m:
            k = root + '/' + m.group(1) + '.less'
            if k not in includes:
                includes[k] = []
            includes[k].append(f)
    if '.git' in dirs:
        dirs.remove('.git')
    towatch += less


watch()
