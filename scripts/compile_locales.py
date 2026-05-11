#!/usr/bin/env python3

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def process_po_file(pofile, attempt=1):
    """Process a single .po file, creating corresponding .mo file."""
    pofile_path = Path(pofile)
    print('processing', pofile_path.as_posix())
    mo_path = pofile_path.with_suffix('.mo')

    mo_path.touch()

    try:
        # Run dennis-cmd lint
        subprocess.run(['dennis-cmd', 'lint', '--errorsonly', pofile], check=True)
        # If lint passes, run msgfmt
        subprocess.run(['msgfmt', '-o', mo_path, pofile], check=True)
        return
    except subprocess.CalledProcessError as e:
        if attempt < 3:
            print(f'Failed attempt {attempt} for {pofile}, retrying...')
            return process_po_file(pofile, attempt=attempt + 1)
        raise e


def compile_locales():
    # Ensure 'dennis' is installed
    import dennis as _dennis  # type: ignore # noqa: F401

    HOME = os.environ.get('HOME')

    locale_dir = Path(HOME) / 'locale'

    print(f'Compiling locales in {locale_dir}')

    futures = []
    with ThreadPoolExecutor() as executor:
        for root, _, files in locale_dir.walk():
            for file in files:
                if file.endswith('.po'):
                    futures.append(executor.submit(process_po_file, root / file))
    [future.result() for future in as_completed(futures)]

if __name__ == '__main__':
    compile_locales()
