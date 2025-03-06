#!/usr/bin/env python3

import argparse
import fnmatch
from pathlib import Path


def clean_dir(path: Path, filter=None, verbose=False):
    if not path.exists():
        return

    for root, dirs, files in path.walk(top_down=False):
        for name in files:
            file_path = root / name
            if not filter or not fnmatch.fnmatch(file_path.as_posix(), filter):
                if verbose:
                    print(f'Removing file {file_path}')
                file_path.unlink()
        for name in dirs:
            dir_path = root / name
            if not filter or not fnmatch.fnmatch(dir_path.as_posix(), filter):
                if verbose:
                    print(f'Removing {dir_path}')
                dir_path.rmdir()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('dir', type=str)
    parser.add_argument('--filter', type=str, required=False)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    path = Path(args.dir)

    clean_dir(path, args.filter, args.verbose)
    path.mkdir(parents=True, exist_ok=True)
