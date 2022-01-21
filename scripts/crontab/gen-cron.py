#!/usr/bin/env python
import os
from optparse import OptionParser


TEMPLATE = open(os.path.join(os.path.dirname(__file__), 'crontab.tpl')).read()


def main():
    parser = OptionParser()
    parser.add_option('-z', '--zamboni', help='Location of addons-server (required)')
    parser.add_option(
        '-u',
        '--user',
        help='Prefix cron with this user. Only define for cron.d style crontabs',
    )
    parser.add_option(
        '-p', '--python', default='/usr/bin/python', help='Python interpreter to use'
    )
    parser.add_option(
        '-d', '--deprecations', default=False, help='Show deprecation warnings'
    )

    (opts, args) = parser.parse_args()

    if not opts.zamboni:
        parser.error('-z must be defined')

    if not opts.deprecations:
        opts.python += ' -W ignore::DeprecationWarning'

    django_cmd = f'{opts.user or ""} cd {opts.zamboni}; {opts.python} manage.py'.strip()
    ctx = {
        'django': django_cmd,
        'z_cron': f'{django_cmd} cron',
        'python': opts.python,
    }

    print(TEMPLATE % ctx)


if __name__ == '__main__':
    main()
