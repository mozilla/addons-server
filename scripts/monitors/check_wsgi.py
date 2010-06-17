#!/usr/bin/python2.6
"""Makes sure mod_wsgi has been restarted after the last code push i.e,
   mod_wsgi is fresher than the mtime on all *.py files in the application dir.
"""
from datetime import datetime
from optparse import OptionParser
import os
from subprocess import PIPE, Popen
import urllib2

def check_modwsgi(app_dir):
    find_ = Popen("find %s -name '*.py'" % app_dir, stdout=PIPE, shell=True).communicate()[0]

    py_files = find_.strip().split("\n")
    newest_mtime = max((os.stat(f).st_mtime, f) for f in py_files)

    req = urllib2.Request("http://localhost:81/z/services/loaded",
                            headers={'Host': 'addons.mozilla.org'})

    mod_wsgi = datetime.strptime(urllib2.urlopen(req).read().strip(), '%Y-%m-%d %H:%M:%S.%f')

    if mod_wsgi < datetime.fromtimestamp(newest_mtime[0]):
        print "CRITICAL: %s is newer than modwsgi (restart apache)" % newest_mtime[1]
        return 2
    else:
        print "OK: mod_wsgi is fresh"
        return 0


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option('-d', '--app_dir',
        help="directory of mod_wsgi app e.g., /data/amo_python/www/prod/zamboni")
    
    options, args = parser.parse_args()

    exit(check_modwsgi(options.app_dir))
