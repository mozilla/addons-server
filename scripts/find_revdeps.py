#!/usr/bin/env python

import pip
import sys
from pip.req import parse_requirements


def rdeps(pkg_name):
    return [pkg.project_name
            for pkg in pip.get_installed_distributions()
            if pkg_name in [requirement.project_name
                            for requirement in pkg.requires()]]


def main(requirements_path):
    apps = sorted([r.name for r in parse_requirements(requirements_path,
                   session=pip.download.PipSession())])
    reverse_requirements = {}
    for app in apps:
        reverse_requirements[app] = rdeps(app)

    for app in sorted(reverse_requirements):
        if reverse_requirements.get(app, None):
            print '# %s is required by %s' % (
                app, ', '.join(reverse_requirements[app]))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print 'Usage: %s <requirement-file>' % sys.argv[0]
        sys.exit(1)
    main(sys.argv[1])
