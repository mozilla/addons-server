import codecs
import mimetypes
import os
import calendar
import zipfile
import hashlib

from collections import OrderedDict

from django.conf import settings
from django.template.defaultfilters import filesizeformat
from django.utils.encoding import force_text
from django.utils.translation import ugettext
from validator.testcases.packagelayout import (
    blacklisted_extensions, blacklisted_magic_numbers)

import olympia.core.logger

from olympia import amo
from olympia.amo.cache_nuggets import Message
from olympia.amo.urlresolvers import reverse
from olympia.lib.cache import cached


task_log = olympia.core.logger.getLogger('z.task')


# Allow files with a shebang through.
denied_magic_numbers = [b for b in list(blacklisted_magic_numbers)
                        if b != (0x23, 0x21)]
denied_extensions = [b for b in list(blacklisted_extensions) if b != 'sh']

LOCKED_LIFETIME = 60 * 5

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


class Sha256CalculatingZipFile(zipfile.ZipFile):
    """ZipFipe that can calculate a sha256 hash while reading the file-data.

    Note that this does not implement strict hash validation with our custom
    hash yet, it simply re-uses CRC validation from the original ZipFile
    implementation. We simply want to calculate the sha256 while
    reading the data anyway.

    Inspired by `wheel`s `VerifyingZipFile` implementation.
    """
    def __init__(self, file, mode="r",
                 compression=zipfile.ZIP_STORED,
                 allowZip64=True):
        super(Sha256CalculatingZipFile, self).__init__(
            file, mode, compression, allowZip64)

        self.strict = False
        self._hash_algorithm = hashlib.sha256

    def open(self, name_or_info, mode='r', pwd=None):
        """Return file-like object for 'name'.

        Overwrite the internal CRC calculation with our own
        hash algoritm.
        """
        ext_file = super(Sha256CalculatingZipFile, self).open(
            name_or_info, mode, pwd)

        _update_crc_orig = ext_file._update_crc

        running_hash = self._hash_algorithm()

        def _update_crc(data, eof=None):
            _update_crc_orig(data, eof=eof)
            running_hash.update(data)

        ext_file._update_crc = _update_crc
        ext_file.running_hash = running_hash

        return ext_file

    def get_sha256(self, name_or_info):
        zobj = self.open(name_or_info)
        # Read into nowhere..
        zobj.read()
        return zobj.running_hash.hexdigest()


def extract_file(viewer, **kw):
    # This message is for end users so they'll see a nice error.
    msg = Message('file-viewer:%s' % viewer)
    msg.delete()
    task_log.debug('Unzipping %s for file viewer.' % viewer)

    try:
        lock_attained = viewer.extract()

        if not lock_attained:
            info_msg = ugettext(
                'File viewer is locked, extraction for %s could be '
                'in progress. Please try again in approximately 5 minutes.'
                % viewer)
            msg.save(info_msg)
    except Exception, exc:
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
        #self.addon = self.file.version.addon
        self.src = file_obj
        self._files, self.selected, self.zip_file = None, None, None

    def __str__(self):
        return str(self.file.id)

    def _cache_key(self, key=None):
        assert key is not None
        return 'file-viewer:{1}:{2}'.format(key, self.file.id)

    def is_search_engine(self):
        """Is our file for a search engine?"""
        return self.file.version.addon.type == amo.ADDON_SEARCH

    def _is_binary(self, mimetype, path):
        """Uses the filename to see if the file can be shown in HTML or not."""
        # Re-use the denied data from amo-validator to spot binaries.
        ext = os.path.splitext(path)[1][1:]
        if ext in denied_extensions:
            return True

        # Don't worry about directories
        if not path[-1] == '/':
            with self.zip_file.open(path, 'r') as rfile:
                bytes = tuple(map(ord, rfile.read(4)))
            if any(bytes[:len(x)] == x for x in denied_magic_numbers):
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
        file_data = self._read_file(allow_empty)
        return file_data

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

        with self.zip_file.open(self.selected['full'], 'r') as opened:
            cont = opened.read()
            self.selected['sha256'] = opened.running_hash.hexdigest()

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
        return files.keys()[0] if files else None  # Eg: it's a search engine.

    def get_files(self):
        """
        Returns an OrderedDict, ordered by the filename of all the files in the
        addon-file. Full of all the useful information you'll need to serve
        this file, build templates etc.
        """
        if self._files:
            return self._files

        self._files = cached(self._get_files, self._cache_key)

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

    def _get_files(self):
        result = OrderedDict()

        # TODO:
        # if self.is_search_engine() and self.src.endswith('.xml'):
        #     shutil.copyfileobj(
        #         storage.open(self.src),
        #         open(os.path.join(self.dest, self.file.filename), 'w'))

        self.zip_file = Sha256CalculatingZipFile(self.src)

        for zip_info in self.zip_file.infolist():
            path = zip_info.filename
            filename = force_text(os.path.basename(path), errors='replace')
            mime, encoding = mimetypes.guess_type(filename)

            # For zip files in the wild there will not always
            # be a directory member where there are files inside that directory
            # Sometimes only the file members will exist, without a separate
            # member for the containing directory. So we'll force the creation
            # of a directory.
            directory = os.path.dirname(path)

            if directory not in result and not directory == '':
                is_directory = True
                path = filename = directory
                modified = size = 0
                is_binary = False
            else:
                is_directory = False
                modified = calendar.timegm(zip_info.date_time)
                size = zip_info.file_size
                is_binary = self._is_binary(mime, path)

            sha256 = self.zip_file.get_sha256(zip_info) if is_binary else '-'
            result[path] = {
                'binary': is_binary,
                'depth': path.count(os.sep),
                'directory': is_directory,
                'filename': filename,
                'short': path,
                'full': path,
                # We still have to calculate the sha256 for binary files
                # on our own. For regular files we can use the on-the-fly
                # calculation from our Sha256CalculatingZipFile.
                'sha256': sha256,
                'mimetype': mime or 'application/octet-stream',
                'syntax': self.get_syntax(filename),
                # TODO: Verify GMT is correct here
                'modified': modified,
                'size': size,
                'truncated': self.truncate(filename),
                'url': reverse(
                    'files.list', args=[0, 'file', path]),
                'url_serve': reverse(
                    'files.redirect', args=[0, path]),
                'version': None,
            }
        return result


class DiffHelper(object):

    def __init__(self, left, right):
        self.left = FileViewer(left)
        self.right = FileViewer(right)
        # self.addon = self.left.addon
        self.key = None

    def __str__(self):
        return '%s:%s' % (self.left, self.right)

    def extract(self):
        self.left.extract(), self.right.extract()

    def cleanup(self):
        self.left.cleanup(), self.right.cleanup()

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
