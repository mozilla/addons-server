#!/usr/bin/env python

import os
import sys
import shlex
from pkg_resources import safe_name

import pip
from pip.req.req_file import parse_requirements, build_parser, break_args_options
from hashin import run_single_package


def rdeps(pkg_name):
    return sorted([safe_name(pkg.project_name)
            for pkg in pip.get_installed_distributions()
            if safe_name(pkg_name) in [
                safe_name(requirement.project_name)
                for requirement in pkg.requires()]])


def main(requirements_path):
    this_requirements_file = os.path.basename(requirements_path)
    parsed = parse_requirements(
        requirements_path, session=pip.download.PipSession())
    requirements = [
        req for req in parsed
            # Skip packages from other requirements files
        if this_requirements_file in req.comes_from]

    reverse_requirements = {}
    nested_requirements = set()

    # Fetch nested reqirements lines, this is mostly copied from
    # pip so that we support stuff "correctly". Unfortunately there
    # isn't any good API in pip for it :-/
    parser = build_parser()
    defaults = parser.get_default_values()

    with open(requirements_path) as fobj:
        for line in fobj:
            args_str, options_str = break_args_options(line)
            opts, _ = parser.parse_args(shlex.split(options_str), defaults)
            if opts.requirements:
                nested_requirements.update(opts.requirements)

    # Build reverse requirements to be able to add a note on who is depending
    # on what
    for req in requirements:
        reverse_requirements[safe_name(req.name)] = rdeps(req.name)

    output = []

    output.extend('-r %s' % req for req in nested_requirements)
    output.append('')

    # Let's output the updated, fixed and more correct requirements version
    for req in sorted(requirements, key=lambda x: safe_name(x.name)):
        if reverse_requirements.get(safe_name(req.name)):
            msg = '# %s is required by %s' % (
                safe_name(req.name),
                ', '.join(reverse_requirements[safe_name(req.name)]))
            output.append(msg)

        output.append('%s%s' % (safe_name(req.name), str(req.specifier)))

    with open(requirements_path, 'wb') as fobj:
        fobj.write('\n'.join(output))

    with open(requirements_path, 'a') as fobj:
        fobj.write('\n')

    for req in requirements:
        run_single_package(
            '%s%s' % (safe_name(req.name), str(req.specifier)),
            requirements_path,
            'sha256',
            # Workaround a bug or feature in hashin which would avoid
            # fetching wheels e.g for some packages.
            python_versions=['py27', '2.7'],
            verbose=True)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: %s <requirement-file>' % sys.argv[0])
        sys.exit(1)
    main(sys.argv[1])
