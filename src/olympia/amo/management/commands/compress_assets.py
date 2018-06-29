import hashlib
import os
import re
import time
import uuid

import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from olympia.lib.jingo_minify_helpers import get_path


def path(*args):
    return os.path.join(settings.STATIC_ROOT, *args)


def run_command(command):
    """Run a command and correctly poll the output and write that to stdout"""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, shell=True)
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print output.strip()
    rc = process.poll()
    return rc


def ensure_path_exists(path):
    try:
        os.makedirs(path)
    except OSError as e:
        # If the directory already exists, that is fine. Otherwise re-raise.
        if e.errno != os.errno.EEXIST:
            raise


class Command(BaseCommand):
    help = ('Compresses css and js assets defined in settings.MINIFY_BUNDLES')
    requires_model_validation = False

    checked_hash = {}
    bundle_hashes = {}

    missing_files = 0
    minify_skipped = 0

    def generate_build_id(self):
        return uuid.uuid4().hex[:8]

    def update_hashes(self):
        # Adds a time based hash on to the build id.
        self.build_id = '%s-%s' % (self.build_id, hex(int(time.time()))[2:])

        build_id_file = os.path.realpath(
            os.path.join(settings.ROOT, 'build.py'))

        with open(build_id_file, 'w') as f:
            f.write('BUILD_ID_CSS = "%s"\n' % self.build_id)
            f.write('BUILD_ID_JS = "%s"\n' % self.build_id)
            f.write('BUILD_ID_IMG = "%s"\n' % self.build_id)
            f.write('BUNDLE_HASHES = %s\n' % self.bundle_hashes)

    def handle(self, **options):
        self.build_id = self.generate_build_id()

        self.verbose = '-v' if options.get('verbosity', False) == '2' else ''

        # This will loop through every bundle, and do the following:
        # - Concat all files into one
        # - Cache bust all images in CSS files
        # - Minify the concatted files
        for ftype, bundle in settings.MINIFY_BUNDLES.iteritems():
            for name, files in bundle.iteritems():
                # Set the paths to the files.
                concatted_file = path(ftype, '%s-all.%s' % (name, ftype,))
                compressed_file = path(ftype, '%s-min.%s' % (name, ftype,))

                ensure_path_exists(os.path.dirname(path(concatted_file)))
                ensure_path_exists(os.path.dirname(path(compressed_file)))

                files_all = []
                for fn in files:
                    processed = self._preprocess_file(fn)
                    # If the file can't be processed, we skip it.
                    if processed is not None:
                        files_all.append(processed)

                # Concat all the files.
                tmp_concatted = '%s.tmp' % concatted_file
                if len(files_all) == 0:
                    raise CommandError(
                        'No input files specified in '
                        'MINIFY_BUNDLES["%s"]["%s"] in settings.py!' %
                        (ftype, name)
                    )
                run_command('cat {files} > {tmp}'.format(
                    files=' '.join(files_all),
                    tmp=tmp_concatted
                ))

                # Cache bust individual images in the CSS.
                if ftype == 'css':
                    bundle_hash = self._cachebust(tmp_concatted, name)
                    self.bundle_hashes['%s:%s' % (ftype, name)] = bundle_hash

                # Compresses the concatenations.
                is_changed = self._is_changed(concatted_file)
                self._clean_tmp(concatted_file)
                if is_changed or not os.path.isfile(compressed_file):
                    self._minify(ftype, concatted_file, compressed_file)
                elif self.verbose:
                    print 'File unchanged, skipping minification of %s' % (
                        concatted_file)
                else:
                    self.minify_skipped += 1

        # Write out the hashes
        self.update_hashes()

        if not self.verbose and self.minify_skipped:
            print 'Unchanged files skipped for minification: %s' % (
                self.minify_skipped)

    def _preprocess_file(self, filename):
        """Preprocess files and return new filenames."""
        css_bin = filename.endswith('.less') and settings.LESS_BIN
        source = get_path(filename)
        target = source
        if css_bin:
            target = '%s.css' % source
            run_command('{lessc} {source} {target}'.format(
                lessc=css_bin,
                source=str(source),
                target=str(target)))
        return target

    def _is_changed(self, concatted_file):
        """Check if the file has been changed."""
        tmp_concatted = '%s.tmp' % concatted_file
        file_exists = (
            os.path.exists(concatted_file) and
            os.path.getsize(concatted_file) == os.path.getsize(tmp_concatted))
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

    def _cachebust(self, css_file, bundle_name):
        """Cache bust images.  Return a new bundle hash."""
        print "Cache busting images in %s" % re.sub('.tmp$', '', css_file)

        if not os.path.exists(css_file):
            return

        css_content = ''
        with open(css_file, 'r') as css_in:
            css_content = css_in.read()

        def _parse(url):
            self._cachebust_regex(url, css_file)

        css_parsed = re.sub('url\(([^)]*?)\)', _parse, css_content)

        with open(css_file, 'w') as css_out:
            css_out.write(css_parsed)

        # Return bundle hash for cachebusting JS/CSS files.
        file_hash = hashlib.md5(css_parsed).hexdigest()[0:7]
        self.checked_hash[css_file] = file_hash

        if not self.verbose and self.missing_files:
            print ' - Error finding %s images (-v2 for info)' % (
                self.missing_files,)
            self.missing_files = 0

        return file_hash

    def _minify(self, ftype, file_in, file_out):
        """Run the proper minifier on the file."""
        if ftype == 'js' and hasattr(settings, 'UGLIFY_BIN'):
            opts = {'method': 'UglifyJS', 'bin': settings.UGLIFY_BIN}
            run_command('{uglify} {verbose} -o {target} {source} -m'.format(
                uglify=opts['bin'],
                verbose=self.verbose,
                target=file_out,
                source=file_in))
        elif ftype == 'css' and hasattr(settings, 'CLEANCSS_BIN'):
            opts = {'method': 'clean-css', 'bin': settings.CLEANCSS_BIN}
            run_command('{cleancss} -o {target} {source}'.format(
                cleancss=opts['bin'],
                target=file_out,
                source=file_in))

        print 'Minifying %s (using %s)' % (file_in, opts['method'])

    def _file_hash(self, url):
        """Open the file and get a hash of it."""
        if url in self.checked_hash:
            return self.checked_hash[url]

        file_hash = ''
        try:
            with open(url) as f:
                file_hash = hashlib.md5(f.read()).hexdigest()[0:7]
        except IOError:
            self.missing_files += 1
            if self.verbose:
                print ' - Could not find file %s' % url

        self.checked_hash[url] = file_hash
        return file_hash

    def _cachebust_regex(self, img, parent):
        """Run over the regex; img is the structural regex object."""
        url = img.group(1).strip('"\'')
        if url.startswith('data:') or url.startswith('http'):
            return 'url(%s)' % url

        url = url.split('?')[0]
        full_url = os.path.join(settings.ROOT, os.path.dirname(parent),
                                url)

        return 'url(%s?%s)' % (url, self._file_hash(full_url))
