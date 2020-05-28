import codecs
import mimetypes
import os
import stat
import shutil

from collections import OrderedDict
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.template.defaultfilters import filesizeformat
from django.utils.encoding import force_text
from django.utils.translation import ugettext

import olympia.core.logger

from olympia import amo
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import rm_local_tmp_dir
from olympia.lib.cache import Message
from olympia.files.utils import (
    lock, extract_xpi, get_all_files, get_sha256)

task_log = olympia.core.logger.getLogger('z.task')

# Detect denied files based on their extension.
denied_extensions = (
    'dll', 'exe', 'dylib', 'so', 'class', 'swf')

denied_magic_numbers = (
    (0x4d, 0x5a),  # EXE/DLL
    (0x5a, 0x4d),  # Alternative for EXE/DLL
    (0x7f, 0x45, 0x4c, 0x46),  # UNIX elf
    (0xca, 0xfe, 0xba, 0xbe),  # Java + Mach-O (dylib)
    (0xca, 0xfe, 0xd0, 0x0d),  # Java (packed)
    (0xfe, 0xed, 0xfa, 0xce),  # Mach-O
    (0x46, 0x57, 0x53),  # Uncompressed SWF
    (0x43, 0x57, 0x53),  # ZLIB compressed SWF
)

SYNTAX_HIGHLIGHTER_ALIAS_MAPPING = {
    'xul': 'xml',
    'rdf': 'xml',
    'jsm': 'js',
    'json': 'js',
    'htm': 'html'
}

# See settings.MINIFY_BUNDLES['js']['zamboni/files'] for more details
# as to which brushes we support.
SYNTAX_HIGHLIGHTER_SUPPORTED_LANGUAGES = frozenset([
    'css', 'html', 'java', 'javascript', 'js', 'jscript',
    'plain', 'text', 'xml', 'xhtml', 'xlst',
])


def extract_file(viewer, **kw):
    # This message is for end users so they'll see a nice error.
    msg = Message('file-viewer:%s' % viewer)
    msg.delete()
    task_log.info('Unzipping %s for file viewer.' % viewer)

    try:
        lock_attained = viewer.extract()

        if not lock_attained:
            info_msg = ugettext(
                'File viewer is locked, extraction for %s could be '
                'in progress. Please try again in approximately 5 minutes.'
                % viewer)
            msg.save(info_msg)
    except Exception as exc:
        error_msg = ugettext('There was an error accessing file %s.') % viewer

        if settings.DEBUG:
            msg.save(error_msg + ' ' + exc)
        else:
            msg.save(error_msg)
        task_log.error('Error unzipping: %s' % exc)

    return msg


class FileViewer(object):
    """
    Provide access to a storage-managed file by copying it locally and
    extracting info from it. `src` is a storage-managed path and `dest` is a
    local temp path.
    """

    def __init__(self, file_obj):
        self.file = file_obj
        self.addon = self.file.version.addon
        self.src = file_obj.current_file_path
        self.base_tmp_path = os.path.join(settings.TMP_PATH, 'file_viewer')
        self.dest = os.path.join(
            self.base_tmp_path,
            datetime.now().strftime('%m%d'),
            str(file_obj.pk))
        self._files, self.selected = None, None

    def __str__(self):
        return str(self.file.id)

    def _cache_key(self):
        return 'file-viewer:{0}'.format(self.file.id)

    def extract(self):
        """
        Will make all the directories and extract the files.
        Raises error on nasty files.

        :returns: `True` if successfully extracted,
                  `False` in case of an existing lock.
        """
        lock_name = f'file-viewer-{self.file.pk}'

        with lock(settings.TMP_PATH, lock_name, timeout=2) as lock_attained:
            if lock_attained:
                if self.is_extracted():
                    # Be vigilent with existing files. It's better to delete
                    # and re-extract than to trust whatever we have
                    # lying around.
                    task_log.warning(
                        'cleaning up %s as there were files lying around'
                        % self.dest)
                    self.cleanup()

                try:
                    os.makedirs(self.dest)
                except OSError as err:
                    task_log.error(
                        'Error (%s) creating directories %s'
                        % (err, self.dest))
                    raise

                if self.is_search_engine() and self.src.endswith('.xml'):
                    shutil.copyfileobj(
                        storage.open(self.src, 'rb'),
                        open(
                            os.path.join(self.dest, self.file.filename), 'wb'))
                else:
                    try:
                        extracted_files = extract_xpi(self.src, self.dest)
                        self._verify_files(extracted_files)
                    except Exception as err:
                        task_log.error(
                            'Error (%s) extracting %s' % (err, self.src))
                        raise

        return lock_attained

    def cleanup(self):
        if os.path.exists(self.dest):
            rm_local_tmp_dir(self.dest)

    def is_search_engine(self):
        """Is our file for a search engine?"""
        return self.file.version.addon.type == amo.ADDON_SEARCH

    def is_extracted(self):
        """If the file has been extracted or not."""
        return os.path.exists(self.dest)

    def _is_binary(self, mimetype, path):
        """Uses the filename to see if the file can be shown in HTML or not."""
        # Re-use the denied data from amo-validator to spot binaries.
        ext = os.path.splitext(path)[1][1:]
        if ext in denied_extensions:
            return True

        if os.path.exists(path) and not os.path.isdir(path):
            with storage.open(path, 'rb') as rfile:
                data = tuple(bytearray(rfile.read(4)))
            if any(data[:len(x)] == x for x in denied_magic_numbers):
                return True

        if mimetype:
            major, minor = mimetype.split('/')
            if major == 'image':
                return 'image'  # Mark that the file is binary, but an image.

        return False

    def read_file(self, allow_empty=False):
        """
        Reads the file. Imposes a file limit and tries to cope with
        UTF-8 and UTF-16 files appropriately. Return file contents and
        a list of error messages.
        """
        try:
            file_data = self._read_file(allow_empty)
            return file_data
        except (IOError, OSError):
            self.selected['msg'] = ugettext('That file no longer exists.')
            return ''

    def _read_file(self, allow_empty=False):
        if not self.selected and allow_empty:
            return ''
        assert self.selected, 'Please select a file'
        if self.selected['size'] > settings.FILE_VIEWER_SIZE_LIMIT:
            # L10n: {0} is the file size limit of the file viewer.
            msg = ugettext(u'File size is over the limit of {0}.').format(
                filesizeformat(settings.FILE_VIEWER_SIZE_LIMIT))
            self.selected['msg'] = msg
            return ''

        with storage.open(self.selected['full'], 'rb') as opened:
            cont = opened.read()
            codec = 'utf-16' if cont.startswith(codecs.BOM_UTF16) else 'utf-8'
            try:
                return cont.decode(codec)
            except UnicodeDecodeError:
                cont = cont.decode(codec, 'ignore')
                # L10n: {0} is the filename.
                self.selected['msg'] = (
                    ugettext('Problems decoding {0}.').format(codec))
                return cont

    def select(self, file_):
        self.selected = self.get_files().get(file_)

    def is_binary(self):
        if self.selected:
            binary = self.selected['binary']
            if binary and (binary != 'image'):
                self.selected['msg'] = ugettext(
                    u'This file is not viewable online. Please download the '
                    u'file to view the contents.')
            return binary

    def is_directory(self):
        if self.selected:
            if self.selected['directory']:
                self.selected['msg'] = ugettext('This file is a directory.')
            return self.selected['directory']

    def get_default(self, key=None):
        """Gets the default file and copes with search engines."""
        if key:
            return key

        files = self.get_files()
        for manifest in ('install.rdf', 'manifest.json', 'package.json'):
            if manifest in files:
                return manifest
        return list(files.keys())[0] if files else None

    def get_files(self):
        """
        Returns an OrderedDict, ordered by the filename of all the files in the
        addon-file. Full of all the useful information you'll need to serve
        this file, build templates etc.
        """
        if self._files:
            return self._files

        if not self.is_extracted():
            extract_file(self)

        self._files = cache.get_or_set(self._cache_key(), self._get_files)
        return self._files

    def truncate(self, filename, pre_length=15,
                 post_length=10, ellipsis=u'..'):
        """
        Truncates a filename so that
           somelongfilename.htm
        becomes:
           some...htm
        as it truncates around the extension.
        """
        root, ext = os.path.splitext(filename)
        if len(root) > pre_length:
            root = root[:pre_length] + ellipsis
        if len(ext) > post_length:
            ext = ext[:post_length] + ellipsis
        return root + ext

    def get_syntax(self, filename):
        """
        Converts a filename into a syntax for the syntax highlighter, with
        some modifications for specific common mozilla files.
        The list of syntaxes is from:
        http://alexgorbatchev.com/SyntaxHighlighter/manual/brushes/
        """
        if filename:
            short = os.path.splitext(filename)[1][1:]
            short = SYNTAX_HIGHLIGHTER_ALIAS_MAPPING.get(short, short)

            if short in SYNTAX_HIGHLIGHTER_SUPPORTED_LANGUAGES:
                return short
        return 'plain'

    def _verify_files(self, expected_files, raise_on_verify=False):
        """Verifies that all files are properly extracted.

        TODO: This should probably be extracted into a separate helper
        once we can verify that it works as expected.
        """
        difference = self._check_dest_for_complete_listing(expected_files)

        if difference:
            if raise_on_verify:
                error_msg = (
                    'Error verifying extraction of %s. Difference: %s' % (
                        self.src, ', '.join(list(difference))))
                task_log.error(error_msg)
                raise ValueError(error_msg)
            else:
                task_log.warning(
                    'Calling fsync, files from %s extraction aren\'t'
                    ' completely available.' % self.src)

                self._fsync_dest_to_complete_listing(
                    self._normalize_file_list(expected_files))

                self._verify_files(expected_files, raise_on_verify=True)

    def _get_files(self, locale=None):
        result = OrderedDict()

        for path in get_all_files(self.dest):
            path = force_text(path, errors='replace')
            filename = os.path.basename(path)
            short = path[len(self.dest) + 1:]
            mime, encoding = mimetypes.guess_type(filename)
            directory = os.path.isdir(path)

            if not directory:
                with open(path, 'rb') as fobj:
                    sha256 = get_sha256(fobj)
            else:
                sha256 = ''

            result[short] = {
                'id': self.file.id,
                'binary': self._is_binary(mime, path),
                'depth': short.count(os.sep),
                'directory': directory,
                'filename': filename,
                'full': path,
                'sha256': sha256,
                'mimetype': mime or 'application/octet-stream',
                'syntax': self.get_syntax(filename),
                'modified': os.stat(path)[stat.ST_MTIME],
                'short': short,
                'size': os.stat(path)[stat.ST_SIZE],
                'truncated': self.truncate(filename),
                'version': self.file.version.version,
            }

        return result

    def _check_dest_for_complete_listing(self, expected_files):
        """Check that all files we expect are in `self.dest`."""
        dest_len = len(self.dest)

        files_to_verify = get_all_files(self.dest)

        difference = (
            set([name[dest_len:].strip('/') for name in files_to_verify]) -
            set(self._normalize_file_list(expected_files)))

        return difference

    def _normalize_file_list(self, expected_files):
        """Normalize file names, strip /tmp/xxxx/ prefix."""
        prefix_len = settings.TMP_PATH.count('/')

        normalized_files = filter(None, (
            fname.strip('/').split('/')[prefix_len + 1:]
            for fname in expected_files
            if fname.startswith(settings.TMP_PATH)))

        normalized_files = [os.path.join(*fname) for fname in normalized_files]

        return normalized_files

    def _fsync_dest_to_complete_listing(self, files):
        # Now call fsync for every single file. This might block for a
        # few milliseconds but it's still way faster than doing any
        # kind of sleeps to wait for writes to happen.
        for fname in files:
            fpath = os.path.join(self.base_tmp_path, fname)
            descriptor = os.open(fpath, os.O_RDONLY)
            os.fsync(descriptor)

        # Then make sure to call fsync on the top-level directory
        top_descriptor = os.open(self.dest, os.O_RDONLY)
        os.fsync(top_descriptor)


class DiffHelper(object):

    def __init__(self, left, right):
        self.left = FileViewer(left)
        self.right = FileViewer(right)
        self.addon = self.left.addon
        self.key = None

    def __str__(self):
        return '%s:%s' % (self.left, self.right)

    def extract(self):
        self.left.extract(), self.right.extract()

    def cleanup(self):
        self.left.cleanup(), self.right.cleanup()

    def is_extracted(self):
        return self.left.is_extracted() and self.right.is_extracted()

    def get_url(self, short):
        return reverse('files.compare',
                       args=[self.left.file.id, self.right.file.id,
                             'file', short])

    def get_files(self):
        """
        Get the files from the primary and:
        - remap any diffable ones to the compare url as opposed to the other
        - highlight any diffs
        """
        left_files = self.left.get_files()
        right_files = self.right.get_files()
        different = []
        for key, file in left_files.items():
            file['url'] = self.get_url(file['short'])
            diff = file['sha256'] != right_files.get(key, {}).get('sha256')
            file['diff'] = diff
            if diff:
                different.append(file)

        # Now mark every directory above each different file as different.
        for diff in different:
            for depth in range(diff['depth']):
                key = '/'.join(diff['short'].split('/')[:depth + 1])
                if key in left_files:
                    left_files[key]['diff'] = True

        return left_files

    def get_deleted_files(self):
        """
        Get files that exist in right, but not in left. These
        are files that have been deleted between the two versions.
        Every element will be marked as a diff.
        """
        different = OrderedDict()
        if self.right.is_search_engine():
            return different

        def keep(path):
            if path not in different:
                copy = dict(right_files[path])
                copy.update({'url': self.get_url(file['short']), 'diff': True})
                different[path] = copy

        left_files = self.left.get_files()
        right_files = self.right.get_files()
        for key, file in right_files.items():
            if key not in left_files:
                # Make sure we have all the parent directories of
                # deleted files.
                dir = key
                while os.path.dirname(dir):
                    dir = os.path.dirname(dir)
                    keep(dir)

                keep(key)

        return different

    def read_file(self):
        """Reads both selected files."""
        return [self.left.read_file(allow_empty=True),
                self.right.read_file(allow_empty=True)]

    def select(self, key):
        """
        Select a file and adds the file object to self.one and self.two
        for later fetching. Does special work for search engines.
        """
        self.key = key
        self.left.select(key)
        if key and self.right.is_search_engine():
            # There's only one file in a search engine.
            key = self.right.get_default()

        self.right.select(key)
        return self.left.selected and self.right.selected

    def is_binary(self):
        """Tells you if both selected files are binary."""
        return (self.left.is_binary() or
                self.right.is_binary())

    def is_diffable(self):
        """Tells you if the selected files are diffable."""
        if not self.left.selected and not self.right.selected:
            return False

        for obj in [self.left, self.right]:
            if obj.is_binary():
                return False
            if obj.is_directory():
                return False
        return True
