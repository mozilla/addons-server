import argparse
import os

from pyupgrade._main import _fix_file


def walkfiles(folder, suffix=''):
    """Iterator over files in folder, recursively."""
    return (
        os.path.join(basename, filename)
        for basename, dirnames, filenames in os.walk(folder)
        for filename in filenames
        if filename.endswith(suffix)
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('targets', nargs='*')
    parser.add_argument('--exit-zero-even-if-changed', action='store_true')
    parser.add_argument('--keep-percent-format', action='store_true')
    parser.add_argument('--keep-mock', action='store_true')
    parser.add_argument('--keep-runtime-typing', action='store_true')
    parser.add_argument(
        '--py38-plus',
        action='store_const', dest='min_version', default=(3, 8), const=(3, 8),
    )
    args = parser.parse_args()

    ret = 0

    for target in args.targets:
        if os.path.isdir(target):
            for filename in walkfiles(target, '.py'):
                ret |= _fix_file(filename, args)
        else:
            ret |= _fix_file(target, args)
    exit(ret)
