#!/usr/bin/env python3

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor


def process_po_file(pofile, attempt=0):
    """Process a single .po file, creating corresponding .mo file."""
    print('processing', pofile)
    directory = os.path.dirname(pofile)
    stem = os.path.splitext(os.path.basename(pofile))[0]
    mo_path = os.path.join(directory, f'{stem}.mo')

    # Touch the .mo file
    open(mo_path, 'a').close()

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


def main():
    # Ensure 'dennis' is installed
    try:
        import dennis as _
    except ImportError:
        print(
            'Error: dennis is not installed. Please install it with pip install dennis'
        )
        exit(1)

    locale_dir = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            '..',
            'locale',
        )
    )

    print(f'Compiling locales in {locale_dir}')

    # Collect all files first
    django_files = []
    djangojs_files = []
    for root, _, files in os.walk(locale_dir):
        for file in files:
            if file == 'django.po':
                django_files.append(os.path.join(root, file))
            elif file == 'djangojs.po':
                djangojs_files.append(os.path.join(root, file))

    # Process django.po files in parallel
    with ThreadPoolExecutor() as executor:
        executor.map(process_po_file, django_files + djangojs_files)


if __name__ == '__main__':
    main()
