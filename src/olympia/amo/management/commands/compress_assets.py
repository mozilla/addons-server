import hashlib
import os
import re
import shutil
import time
import urllib2
import uuid

from subprocess import PIPE, call, check_output

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from olympia.lib.jingo_minify_helpers import get_media_root, get_path


def path(*args):
    return os.path.join(get_media_root(), *args)


class Command(BaseCommand):
    help = ('Compresses css and js assets defined in settings.MINIFY_BUNDLES')
    requires_model_validation = False
    do_update_only = False

    checked_hash = {}
    bundle_hashes = {}

    missing_files = 0
    minify_skipped = 0
    cmd_errors = False
    ext_media_path = os.path.join(get_media_root(), 'external')

    def add_arguments(self, parser):
        parser.add_argument(
            '--use-uuid', action='store_true', dest='use_uuid',
            help='Use a uuid as the build id instead of git.')
        parser.add_argument(
            '-u', '--update-only', action='store_true', dest='do_update_only',
            help='Updates the hash only')
        parser.add_argument(
            '-t', '--add-timestamp', action='store_true', dest='add_timestamp',
            help='Add timestamp to hash')

    def generate_build_id(self, use_uuid):
        if use_uuid:
            return uuid.uuid4().hex[:8]
        else:
            root = getattr(settings, 'JINGO_MINIFY_ASSETS_GIT_ROOT', '.')
            git_bin = getattr(settings, 'GIT_BIN', 'git')
            return check_output(
                [git_bin, '-C', root, 'rev-parse', '--short', 'HEAD']).strip()

    def update_hashes(self, update=False):
        if update:
            # Adds a time based hash on to the build id.
            self.build_id = '%s-%s' % (
                self.build_id, hex(int(time.time()))[2:])

        build_id_file = os.path.realpath(os.path.join(settings.ROOT,
                                                      'build.py'))
        with open(build_id_file, 'w') as f:
            f.write('BUILD_ID_CSS = "%s"\n' % self.build_id)
            f.write('BUILD_ID_JS = "%s"\n' % self.build_id)
            f.write('BUILD_ID_IMG = "%s"\n' % self.build_id)
            f.write('BUNDLE_HASHES = %s\n' % self.bundle_hashes)

    def handle(self, **options):
        self.build_id = self.generate_build_id(options.get('use_uuid', False))

        if options.get('do_update_only', False):
            self.update_hashes(update=True)
            return

        jar_path = (os.path.dirname(__file__), '..', '..', 'bin',
                    'yuicompressor-2.4.7.jar')
        self.path_to_jar = os.path.realpath(os.path.join(*jar_path))

        self.v = '-v' if options.get('verbosity', False) == '2' else ''

        cachebust_imgs = getattr(settings, 'CACHEBUST_IMGS', False)
        if not cachebust_imgs:
            print 'To turn on cache busting, use settings.CACHEBUST_IMGS'

        # This will loop through every bundle, and do the following:
        # - Concat all files into one
        # - Cache bust all images in CSS files
        # - Minify the concatted files

        for ftype, bundle in settings.MINIFY_BUNDLES.iteritems():
            for name, files in bundle.iteritems():
                # Set the paths to the files.
                concatted_file = path(ftype, '%s-all.%s' % (name, ftype,))
                compressed_file = path(ftype, '%s-min.%s' % (name, ftype,))

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
                self._call(
                    'cat %s > %s' % (' '.join(files_all), tmp_concatted),
                    shell=True
                )

                # Cache bust individual images in the CSS.
                if cachebust_imgs and ftype == "css":
                    bundle_hash = self._cachebust(tmp_concatted, name)
                    self.bundle_hashes["%s:%s" % (ftype, name)] = bundle_hash

                # Compresses the concatenations.
                is_changed = self._is_changed(concatted_file)
                self._clean_tmp(concatted_file)
                if is_changed or not os.path.isfile(compressed_file):
                    self._minify(ftype, concatted_file, compressed_file)
                elif self.v:
                    print 'File unchanged, skipping minification of %s' % (
                        concatted_file)
                else:
                    self.minify_skipped += 1

        # Write out the hashes
        self.update_hashes(options.get('add_timestamp', False))

        if not self.v and self.minify_skipped:
            print 'Unchanged files skipped for minification: %s' % (
                self.minify_skipped)
        if self.cmd_errors:
            raise CommandError('one or more minify commands exited with a '
                               'non-zero status. See output above for errors.')

    def _call(self, *args, **kw):
        exit = call(*args, **kw)
        if exit != 0:
            print '%s exited with a non-zero status.' % args
            self.cmd_errors = True
        return exit

    def _get_url_or_path(self, item):
        """
        Determine whether this is a URL or a relative path.
        """
        if item.startswith('//'):
            return 'http:%s' % item
        elif item.startswith(('http', 'https')):
            return item
        return None

    def _preprocess_file(self, filename):
        """Preprocess files and return new filenames."""
        url = self._get_url_or_path(filename)
        if url:
            # External files from URLs are placed into a subdirectory.
            if not os.path.exists(self.ext_media_path):
                os.makedirs(self.ext_media_path)

            filename = os.path.basename(url)
            if filename.endswith(('.js', '.css', '.less', '.styl')):
                fp = path(filename.lstrip('/'))
                file_path = '%s/%s' % (self.ext_media_path, filename)

                try:
                    req = urllib2.urlopen(url)
                    print ' - Fetching %s ...' % url
                except urllib2.HTTPError, e:
                    print ' - HTTP Error %s for %s, %s' % (url, filename,
                                                           str(e.code))
                    return None
                except urllib2.URLError, e:
                    print ' - Invalid URL %s for %s, %s' % (url, filename,
                                                            str(e.reason))
                    return None

                with open(file_path, 'w+') as fp:
                    try:
                        shutil.copyfileobj(req, fp)
                    except shutil.Error:
                        print ' - Could not copy file %s' % filename
                filename = os.path.join('external', filename)
            else:
                print ' - Not a valid remote file %s' % filename
                return None

        css_bin = (
            (filename.endswith('.less') and settings.LESS_BIN) or
            (filename.endswith(('.sass', '.scss')) and settings.SASS_BIN)
        )
        fp = get_path(filename)
        if css_bin:
            self._call('%s %s %s.css' % (css_bin, fp, fp),
                       shell=True, stdout=PIPE)
            fp = '%s.css' % fp
        elif filename.endswith('.styl'):
            self._call('%s --include-css --include %s < %s > %s.css' %
                       (settings.STYLUS_BIN, os.path.dirname(fp), fp, fp),
                       shell=True, stdout=PIPE)
            fp = '%s.css' % fp
        return fp

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

        if not self.v and self.missing_files:
            print ' - Error finding %s images (-v2 for info)' % (
                self.missing_files,)
            self.missing_files = 0

        return file_hash

    def _minify(self, ftype, file_in, file_out):
        """Run the proper minifier on the file."""
        if ftype == 'js' and hasattr(settings, 'UGLIFY_BIN'):
            o = {'method': 'UglifyJS', 'bin': settings.UGLIFY_BIN}
            self._call(
                '%s %s -o %s %s -m' % (o['bin'], self.v, file_out, file_in),
                shell=True, stdout=PIPE)
        elif ftype == 'css' and hasattr(settings, 'CLEANCSS_BIN'):
            o = {'method': 'clean-css', 'bin': settings.CLEANCSS_BIN}
            self._call('%s -o %s %s' % (o['bin'], file_out, file_in),
                       shell=True, stdout=PIPE)
        else:
            o = {'method': 'YUI Compressor', 'bin': settings.JAVA_BIN}
            variables = (o['bin'], self.path_to_jar, self.v, file_in, file_out)
            self._call('%s -jar %s %s %s -o %s' % variables,
                       shell=True, stdout=PIPE)

        print 'Minifying %s (using %s)' % (file_in, o['method'])

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
            if self.v:
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
