#!/usr/bin/env python3

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def process_po_file(pofile, attempt=1):
    """Process a single .po file, creating corresponding .mo file."""
    pofile_path = Path(pofile)
    print('processing', pofile_path.as_posix())
    mo_path = pofile_path.with_suffix('.mo')

    mo_path.touch()

    try:
        # Run dennis-cmd lint
        subprocess.run(
            ['dennis-cmd', 'lint', '--errorsonly', pofile],
            capture_output=True,
            check=False,
        )
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

    # Collect all files first
    django_files = []
    djangojs_files = []
    for root, _, files in locale_dir.walk():
        for file in files:
            if file == 'django.po':
                django_files.append(root / file)
            elif file == 'djangojs.po':
                djangojs_files.append(root / file)

    # Process django.po files in parallel
    with ThreadPoolExecutor() as executor:
        executor.map(process_po_file, django_files + djangojs_files)


if __name__ == '__main__':
    compile_locales()
