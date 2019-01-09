import os

from collections import OrderedDict

from django.conf import settings
from django.template.defaultfilters import filesizeformat
from django.utils.translation import ugettext, get_language

import olympia.core.logger

from olympia import amo
from olympia.amo.urlresolvers import reverse
from olympia.lib.cache import Message
from olympia.lib.git import AddonGitRepository, ExtractionAlreadyInProgress


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


class FileViewer(object):
    """
    Helper around git-storage managed files. Primarily used to keep our
    old file-viewer alive while we're working on something new, rest-api based.
    """

    def __init__(self, file_obj):
        self.file = file_obj
        self.addon = self.file.version.addon
        self._files, self.selected = None, None
        self.repository = AddonGitRepository(self.addon.pk)

    def __str__(self):
        return str(self.file.id)

    def _cache_key(self):
        return 'file-viewer:{0}'.format(self.file.id)

    def is_search_engine(self):
        """Is our file for a search engine?"""
        return self.file.version.addon.type == amo.ADDON_SEARCH

    def is_extracted(self):
        """If the file has been extracted or not."""
        return self.repository.is_extracted

    def get_serializer(self):
        from olympia.reviewers.serializers import AddonFileBrowseSerializer
        return AddonFileBrowseSerializer(
            context={
                'file': self.selected['path'] if self.selected else None},
            instance=self.file
        )

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

        return self.get_serializer().get_content(self.file)

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

    def extract(self):
        msg = Message('file-viewer:%s' % self)
        msg.delete()

        task_log.debug('Unzipping %s for file viewer.' % self)

        try:
            self.repository.extract_and_commit_from_version(
                self.file.version)
        except ExtractionAlreadyInProgress:
            info_msg = ugettext(
                'File viewer is locked, extraction for %s could be '
                'in progress. Please try again in approximately 5 minutes.'
                % self)
            msg.save(info_msg)
            return False
        except Exception as exc:
            error_msg = (
                ugettext('There was an error accessing file %s.')
                % self)

            if settings.DEBUG:
                msg.save(error_msg + ' ' + exc)
            else:
                msg.save(error_msg)
            task_log.error('Error unzipping: %s' % exc)
            return False
        return True

    def get_files(self):
        """
        Returns an OrderedDict, ordered by the filename of all the files in the
        addon-file. Full of all the useful information you'll need to serve
        this file, build templates etc.
        """
        if self._files:
            return self._files

        if not self.is_extracted():
            self.extract()

        self._files = self._get_files()
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

    def get_selected_file(self):
        """Gets the selected or default file and copes with search engines."""
        # We are caching `files` here in the file-viewer instance for now,
        # use that and forward to the serializer.
        files = self.get_files()
        return self.get_serializer().get_selected_file(files=files)

    def _get_files(self):
        files = self.get_serializer().get_files(self.file)

        for file_data in files.values():
            # Inject file-viewer specific data that is required in
            # the templates.
            file_data.update({
                'syntax': self.get_syntax(file_data['filename']),
                'truncated': self.truncate(file_data['filename']),
            })

        return files


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

    def get_url(self, filename):
        return reverse('files.compare',
                       args=[self.left.file.id, self.right.file.id,
                             'file', filename])

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
            file['url'] = self.get_url(file['path'])
            diff = file['sha256'] != right_files.get(key, {}).get('sha256')
            file['diff'] = diff
            if diff:
                different.append(file)

        # Now mark every directory above each different file as different.
        for diff in different:
            for depth in range(diff['depth']):
                key = '/'.join(diff['path'].split('/')[:depth + 1])
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
                copy.update({
                    'url': self.get_url(file['path']),
                    'diff': True})
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
            key = self.right.get_selected_file()

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
