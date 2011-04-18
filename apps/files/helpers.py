import codecs
import mimetypes
import os
import shutil
import stat

from django.conf import settings
from django.utils.datastructures import SortedDict
from django.utils.encoding import smart_unicode

import commonware.log
from jingo import register
from tower import ugettext as _

from amo.utils import memoize
from amo.urlresolvers import reverse
from files.utils import extract_xpi, get_md5


task_log = commonware.log.getLogger('z.task')


@register.function
def file_viewer_class(value, selected):
    result = []
    if value['directory']:
        result.append('directory closed')
    else:
        result.append('file')
    if selected and value['short'] == selected['short']:
        result.append('selected')
    return ' '.join(result)


class FileViewer:

    def __init__(self, file_obj):
        self.file = file_obj
        self.src = file_obj.file_path
        self.dest = os.path.join(settings.TMP_PATH, 'file_viewer',
                                 str(file_obj.pk))
        self._files = None

    def __str__(self):
        return str(self.file.id)

    def extract(self):
        """
        Will make all the directories and expand the files.
        Raises error on nasty files.
        """
        try:
            os.makedirs(self.dest)
        except OSError:
            return
        try:
            extract_xpi(self.src, self.dest)
        except Exception, err:
            task_log.error('Error (%s) extracting %s' % (err, self.src))

    def cleanup(self):
        if os.path.exists(self.dest):
            shutil.rmtree(self.dest)

    @property
    def is_extracted(self):
        """If the file has been extracted or not."""
        return os.path.exists(self.dest)

    def is_binary(self, mimetype, filename):
        """Uses the filename to see if the file can be shown in HTML or not."""
        if mimetype:
            major, minor = mimetype.split('/')
            if major == 'text' and minor in ['plain', 'html']:
                return False
            elif minor in ['xml', 'rdf+xml', 'javascript', 'x-javascript',
                         'xml-dtd', 'vnd.mozilla.xul+xml']:
                return False
        elif os.path.splitext(filename)[1] in ['.dtd', '.xul', '.properties']:
            return False
        return True

    def read_file(self, selected):
        with open(selected['full'], 'r') as opened:
            cont = opened.read()
            codec = 'utf-16' if cont.startswith(codecs.BOM_UTF16) else 'utf-8'
            try:
                return cont.decode(codec), ''
            except UnicodeDecodeError:
                cont = cont.decode(codec, 'ignore')
                #L10n: {0} is the filename.
                return cont, _('Problems decoding using: %s.' % codec)

    def get_files(self):
        """
        Returns a SortedDict, ordered by the filename of all the files in the
        addon-file. Full of all the useful information you'll need to serve
        this file, build templates etc.
        """
        if not self.is_extracted:
            return {}
        return self._get_files()

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

    @memoize(prefix='file-viewer')
    def _get_files(self):
        all_files, res = [], SortedDict()
        for root, dirs, files in os.walk(self.dest):
            for filename in dirs + files:
                all_files.append([os.path.join(root, filename), filename])

        for path, filename in sorted(all_files):
            filename = smart_unicode(filename)
            short = smart_unicode(path[len(self.dest) + 1:])
            mime, encoding = mimetypes.guess_type(filename)
            binary = self.is_binary(mime, filename)
            # TODO: handling for st.a.m.o will be going in here
            url = reverse('files.list', args=[self.file.id, short])
            directory = os.path.isdir(path)
            res[short] = {'full': path,
                          'filename': filename,
                          'truncated': self.truncate(filename),
                          'short': short,
                          'directory': directory,
                          'url': url,
                          'binary': binary,
                          'depth': short.count(os.sep),
                          'modified': os.stat(path)[stat.ST_MTIME],
                          'mimetype': mime or 'application/octet-stream',
                          'encoding': encoding,
                          'md5': get_md5(path) if not directory else '',
                          'parent': '/'.join(short.split(os.sep)[:-1])}
        return res


class DiffHelper:

    def __init__(self, file_one_obj, file_two_obj):
        self.file_one = FileViewer(file_one_obj)
        self.file_two = FileViewer(file_two_obj)
        self.status, self.one, self.two = None, None, None

    def __str__(self):
        return '%s, %s' % (self.file_one, self.file_two)

    def extract(self):
        self.file_one.extract()
        self.file_two.extract()

    def cleanup(self):
        self.file_one.cleanup()
        self.file_two.cleanup()

    @property
    def is_extracted(self):
        return self.file_one.is_extracted and self.file_two.is_extracted

    def primary_files(self):
        """
        Get the files from the primary and remap any diffable ones
        to the compare url as opposed to the other url.
        """
        files = self.file_one.get_files()
        for file in files.values():
            file['url'] = reverse('files.compare',
                                  args=[self.file_one.file.id,
                                        self.file_two.file.id,
                                        file['short']])

        return files

    def select(self, key):
        self.key = key
        self.one = self.file_one.get_files().get(key)
        self.two = self.file_two.get_files().get(key)

    def is_different(self):
        if self.one and self.two:
            return self.one['md5'] != self.two['md5']

    def is_binary(self):
        if self.one and self.two:
            return self.one['binary'] or self.two['binary']

    def is_diffable(self):
        if not self.one and not self.two:
            return False

        for obj, selected in ([self.file_one.file, self.one],
                              [self.file_two.file, self.two]):
            if not selected:
                self.status = _('%s does not exist in file %s.' %
                                (self.key, obj.id))
                return False
            if selected['directory']:
                self.status = _('%s is a directory in file %s.' %
                                (self.key, obj.id))
                return False
        return True
