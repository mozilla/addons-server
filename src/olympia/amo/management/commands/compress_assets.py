import hashlib
import os
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.staticfiles.finders import find as find_static_path

from olympia.lib.jingo_minify_helpers import ensure_path_exists


def run_command(command):
    """Run a command and correctly poll the output and write that to stdout"""
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, shell=True, universal_newlines=True
    )
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(output.strip())
    return process.poll()


class Command(BaseCommand):
    help = 'Compresses css and js assets defined in settings.MINIFY_BUNDLES'

    # This command must not do any system checks because Django runs db-field
    # related checks since 1.10 which require a working MySQL connection.
    # We don't have that during our docker builds and since `compress_assets`
    # is being used while building our docker images we have to disable them.
    requires_system_checks = False

    checked_hash = {}

    missing_files = 0
    minify_skipped = 0

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--force',
            action='store_true',
            help='Ignores modified/created dates and forces compression.',
        )

    def handle(self, **options):
        self.force_compress = options.get('force', False)

        # This will loop through every bundle, and do the following:
        # - Concat all files into one
        # - Cache bust all images in CSS files
        # - Minify the concatted files
        for ftype, bundle in settings.MINIFY_BUNDLES.items():
            for name, files in bundle.items():
                # Set the paths to the files.
                concatted_file = os.path.join(
                    settings.ROOT,
                    'static',
                    ftype,
                    '%s-all.%s'
                    % (
                        name,
                        ftype,
                    ),
                )
                compressed_file = os.path.join(
                    settings.ROOT,
                    'static',
                    ftype,
                    '%s-min.%s'
                    % (
                        name,
                        ftype,
                    ),
                )

                ensure_path_exists(concatted_file)
                ensure_path_exists(compressed_file)

                files_all = []
                contents = []
                for filename in files:
                    processed = self._preprocess_file(filename)
                    # If the file can't be processed, we skip it.
                    if processed is not None:
                        files_all.append(processed)
                    with open(processed) as f:
                        contents.append(f.read())

                # Concat all the files.
                tmp_concatted = '%s.tmp' % concatted_file
                if len(files_all) == 0:
                    raise CommandError(
                        'No input files specified in '
                        'MINIFY_BUNDLES["%s"]["%s"] in settings.py!' % (ftype, name)
                    )
                with open(tmp_concatted, 'w') as f:
                    f.write(''.join(contents))

                # Compresses the concatenations.
                is_changed = self._is_changed(concatted_file)
                self._clean_tmp(concatted_file)
                if is_changed or not os.path.isfile(compressed_file):
                    self._minify(ftype, concatted_file, compressed_file)
                else:
                    print(
                        'File unchanged, skipping minification of %s' % (concatted_file)
                    )
                    self.minify_skipped += 1

        if self.minify_skipped:
            print(
                'Unchanged files skipped for minification: %s' % (self.minify_skipped)
            )

    def _preprocess_file(self, filename):
        """Preprocess files and return new filenames."""
        css_bin = filename.endswith('.less') and settings.LESS_BIN
        source = find_static_path(filename)
        target = source
        if css_bin:
            target = '%s.css' % source
            run_command(
                '{lessc} {source} {target}'.format(
                    lessc=css_bin, source=str(source), target=str(target)
                )
            )
        return target

    def _is_changed(self, concatted_file):
        """Check if the file has been changed."""
        if self.force_compress:
            return True

        tmp_concatted = '%s.tmp' % concatted_file
        file_exists = os.path.exists(concatted_file) and os.path.getsize(
            concatted_file
        ) == os.path.getsize(tmp_concatted)
        if file_exists:
            orig_hash = self._file_hash(concatted_file)
            temp_hash = self._file_hash(tmp_concatted)
            return orig_hash != temp_hash
        return True  # Different filesize, so it was definitely changed

    def _clean_tmp(self, concatted_file):
        """Replace the old file with the temp file."""
        tmp_concatted = '%s.tmp' % concatted_file
        if os.path.exists(concatted_file):
            os.remove(concatted_file)
        os.rename(tmp_concatted, concatted_file)

    def _minify(self, ftype, file_in, file_out):
        """Run the proper minifier on the file."""
        if ftype == 'js' and hasattr(settings, 'JS_MINIFIER_BIN'):
            opts = {'method': 'terser', 'bin': settings.JS_MINIFIER_BIN}
            run_command(
                '{bin} --compress --mangle -o {target} {source} -m'.format(
                    bin=opts['bin'], target=file_out, source=file_in
                )
            )
        elif ftype == 'css' and hasattr(settings, 'CLEANCSS_BIN'):
            opts = {'method': 'clean-css', 'bin': settings.CLEANCSS_BIN}
            run_command(
                '{cleancss} -o {target} {source}'.format(
                    cleancss=opts['bin'], target=file_out, source=file_in
                )
            )

        self.stdout.write('Minifying {} (using {})\n'.format(file_in, opts['method']))

    def _file_hash(self, url):
        """Open the file and get a hash of it."""
        if url in self.checked_hash:
            return self.checked_hash[url]

        file_hash = ''
        try:
            with open(url, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()[0:7]
        except OSError:
            self.missing_files += 1
            self.stdout.write(' - Could not find file %s\n' % url)

        self.checked_hash[url] = file_hash
        return file_hash
