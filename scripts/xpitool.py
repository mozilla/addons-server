#!/usr/bin/env python
import optparse
import os
import subprocess


def main():
    p = optparse.OptionParser(
        usage='%prog [options] [-x addon-1.0.xpi] [-c /path/to/addon-1.0/]')
    p.add_option('-x', '--extract',
                 help='Extracts xpi into current directory',
                 action='store_true')
    p.add_option('-c', '--recreate',
                 help='Zips an extracted xpi into current directory',
                 action='store_true')
    (options, args) = p.parse_args()
    if len(args) != 1:
        p.error("Incorrect usage")
    addon = os.path.abspath(args[0])
    if options.extract:
        d = os.path.splitext(addon)[0]
        os.mkdir(d)
        os.chdir(d)
        subprocess.check_call(['unzip', addon])
        print "Extracted to %s" % d
    elif options.recreate:
        xpi = "%s.xpi" % addon
        if os.path.exists(xpi):
            p.error("Refusing to overwrite %r" % xpi)
        os.chdir(addon)
        subprocess.check_call(['zip', '-r', xpi] + os.listdir(os.getcwd()))
        print "Created %s" % xpi
    else:
        p.error("Incorrect usage")


if __name__ == '__main__':
    main()
