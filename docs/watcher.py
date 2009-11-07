"""
Watch a bunch of files and run a command if any changes are detected.

Usage
-----
::

    python watcher.py 'echo changes' one.py two.py

To automatically keep Sphinx docs up to date::

    python watcher.py 'make html' $(find . -name '*.rst')

Problems
--------

 * The file checking would be way more efficient using inotify or whatever the
   equivalent is on OS X.
 * It doesn't handle bad input or spaces in filenames.

But it works for me.
"""
import os
import sys
import time


_mtimes = {}


def timecheck(files):
    """Return True if any of the files have changed."""
    global _mtimes
    for filename in files:
        mtime = os.stat(filename).st_mtime
        if filename not in _mtimes:
            _mtimes[filename] = mtime
        elif mtime != _mtimes[filename]:
            _mtimes = {}
            return True
    else:
        return False


def watcher(command, files):
    """Run ``command`` if any file in ``files`` changes."""
    while True:
        if timecheck(files):
            os.system(command)
        time.sleep(1)


def main():
    command, files = sys.argv[1], sys.argv[2:]
    try:
        watcher(command, files)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
