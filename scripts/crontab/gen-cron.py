#!/usr/bin/env python
import os
from optparse import OptionParser


TEMPLATE = open(os.path.join(os.path.dirname(__file__), 'crontab.tpl')).read()


def main():
    parser = OptionParser()
    parser.add_option("-z", "--zamboni",
                      help="Location of zamboni (required)")
    parser.add_option("-u", "--user",
                      help=("Prefix cron with this user. "
                            "Only define for cron.d style crontabs"))
    parser.add_option("-p", "--python", default="/usr/bin/python2.7",
                      help="Python interpreter to use")
    parser.add_option("-d", "--deprecations", default=False,
                      help="Show deprecation warnings")

    (opts, args) = parser.parse_args()

    if not opts.zamboni:
        parser.error("-z must be defined")

    if not opts.deprecations:
        opts.python += ' -W ignore::DeprecationWarning'

    ctx = {'django': 'cd %s; %s manage.py' % (opts.zamboni, opts.python)}
    ctx['z_cron'] = '%s cron' % ctx['django']

    if opts.user:
        for k, v in ctx.iteritems():
            ctx[k] = '%s %s' % (opts.user, v)

    # Needs to stay below the opts.user injection.
    ctx['python'] = opts.python

    print(TEMPLATE % ctx)


if __name__ == "__main__":
    main()
