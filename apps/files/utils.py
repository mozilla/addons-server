import collections
import cPickle as pickle
import glob
import hashlib
import logging
import os
import re
import shutil
import stat
import StringIO
import tempfile
import zipfile
from datetime import datetime
from itertools import groupby
from xml.dom import minidom
from zipfile import BadZipfile

from django import forms
from django.conf import settings

import rdflib
import redisutils
from tower import ugettext as _

import amo
from applications.models import AppVersion
from versions.compare import version_int as vint


log = logging.getLogger('files.utils')


class ParseError(forms.ValidationError):
    pass


VERSION_RE = re.compile('^[-+*.\w]{,32}$')


class Extractor(object):
    """Extract add-on info from an install.rdf."""
    TYPES = {'2': amo.ADDON_EXTENSION, '4': amo.ADDON_THEME,
             '8': amo.ADDON_LPAPP}
    App = collections.namedtuple('App', 'appdata id min max')
    manifest = u'urn:mozilla:install-manifest'

    def __init__(self, path):
        self.path = path
        self.rdf = rdflib.Graph().parse(open(os.path.join(path,
                                                          'install.rdf')))
        self.find_root()
        self.data = {
            'guid': self.find('id'),
            'type': self.find_type(),
            'name': self.find('name'),
            'version': self.find('version'),
            'homepage': self.find('homepageURL'),
            'summary': self.find('description'),
            'no_restart': self.find('bootstrap') == 'true',
            'apps': self.apps(),
        }

    @classmethod
    def parse(cls, install_rdf):
        return cls(install_rdf).data

    def find_type(self):
        # Look for themes.
        if self.path.endswith('.jar') or self.find('internalName'):
            return amo.ADDON_THEME

        # Look for dictionaries.
        dic = os.path.join(self.path, 'dictionaries')
        if os.path.exists(dic) and glob.glob('%s/*.dic' % dic):
            return amo.ADDON_DICT

        # Consult <em:type>.
        return self.TYPES.get(self.find('type'), amo.ADDON_EXTENSION)

    def uri(self, name):
        namespace = 'http://www.mozilla.org/2004/em-rdf'
        return rdflib.term.URIRef('%s#%s' % (namespace, name))

    def find_root(self):
        # If the install-manifest root is well-defined, it'll show up when we
        # search for triples with it.  If not, we have to find the context that
        # defines the manifest and use that as our root.
        # http://www.w3.org/TR/rdf-concepts/#section-triples
        manifest = rdflib.term.URIRef(self.manifest)
        if list(self.rdf.triples((manifest, None, None))):
            self.root = manifest
        else:
            self.root = self.rdf.subjects(None, self.manifest).next()

    def find(self, name, ctx=None):
        """Like $() for install.rdf, where name is the selector."""
        if ctx is None:
            ctx = self.root
        # predicate it maps to <em:{name}>.
        match = list(self.rdf.objects(ctx, predicate=self.uri(name)))
        # These come back as rdflib.Literal, which subclasses unicode.
        if match:
            return unicode(match[0])

    def apps(self):
        rv = []
        for ctx in self.rdf.objects(None, self.uri('targetApplication')):
            app = amo.APP_GUIDS.get(self.find('id', ctx))
            if not app:
                continue
            try:
                qs = AppVersion.objects.filter(application=app.id)
                min = qs.get(version=self.find('minVersion', ctx))
                max = qs.get(version=self.find('maxVersion', ctx))
            except AppVersion.DoesNotExist:
                continue
            rv.append(self.App(appdata=app, id=app.id, min=min, max=max))
        return rv


def extract_search(content):
    rv = {}
    dom = minidom.parse(content)
    text = lambda x: dom.getElementsByTagName(x)[0].childNodes[0].wholeText
    rv['name'] = text('ShortName')
    rv['description'] = text('Description')
    return rv


def parse_search(filename, addon=None):
    try:
        data = extract_search(open(filename))
    except forms.ValidationError:
        raise
    except Exception:
        log.error('OpenSearch parse error', exc_info=True)
        raise forms.ValidationError(_('Could not parse %s.') % filename)

    return {'guid': None,
            'type': amo.ADDON_SEARCH,
            'name': data['name'],
            'summary': data['description'],
            'version': datetime.now().strftime('%Y%m%d')}


class SafeUnzip(object):
    def __init__(self, source):
        self.source = source
        self.info = None

    def is_valid(self, fatal=True):
        """
        Runs some overall archive checks.
        fatal: if the archive is not valid and fatal is True, it will raise
               an error, otherwise it will return False.
        """
        try:
            zip = zipfile.ZipFile(self.source)
        except (BadZipfile, IOError), err:
            log.error('Error (%s) extracting %s' % (err, self.source))
            if fatal:
                raise
            return False

        _info = zip.infolist()

        for info in _info:
            if '..' in info.filename or info.filename.startswith('/'):
                log.error('Extraction error, Invalid archive: %s' %
                          self.source)
                raise forms.ValidationError(_('Invalid archive.'))

            if info.file_size > settings.FILE_UNZIP_SIZE_LIMIT:
                log.error('Extraction error, file too big: %s, %s'
                          % (self.source, info.file_size))
                raise forms.ValidationError(_('Invalid archive.'))

        self.info = _info
        self.zip = zip
        return True

    def extract_from_manifest(self, manifest):
        """
        Extracts a file given a manifest such as:
            jar:chrome/de.jar!/locale/de/browser/
        or
            locale/de/browser
        """
        type, path = manifest.split(':')
        jar = self
        if type == 'jar':
            parts = path.split('!')
            for part in parts[:-1]:
                jar = self.__class__(StringIO.StringIO(jar.zip.read(part)))
                jar.is_valid(fatal=True)
            path = parts[-1]
        return jar.extract_path(path[1:] if path.startswith('/') else path)

    def extract_path(self, path):
        """Given a path, extracts the content at path."""
        return self.zip.read(path)

    def extract_info_to_dest(self, info, dest):
        """Extracts the given info to a directory and checks the file size."""
        self.zip.extract(info, dest)
        dest = os.path.join(dest, info.filename)
        if not os.path.isdir(dest):
            # Directories consistently report their size incorrectly.
            size = os.stat(dest)[stat.ST_SIZE]
            if size != info.file_size:
                log.error('Extraction error, uncompressed size: %s, %s not %s'
                          % (self.source, size, info.file_size))
                raise forms.ValidationError(_('Invalid archive.'))

    def extract_to_dest(self, dest):
        """Extracts the zip file to a directory."""
        for info in self.info:
            self.extract_info_to_dest(info, dest)


def extract_zip(source, remove=False, fatal=True):
    """Extracts the zip file. If remove is given, removes the source file."""
    tempdir = tempfile.mkdtemp()

    zip = SafeUnzip(source)
    if zip.is_valid(fatal):
        zip.extract_to_dest(tempdir)

    if remove:
        os.remove(source)
    return tempdir


def copy_over(source, dest):
    """
    Copies from the source to the destination, removing the destination
    if it exists and is a directory.
    """
    if os.path.exists(dest) and os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    shutil.rmtree(source)


def extract_xpi(xpi, path, expand=False):
    """
    If expand is given, will look inside the expanded file
    and find anything in the whitelist and try and expand it as well.
    It will do up to 10 iterations, after that you are on your own.

    It will replace the expanded file with a directory and the expanded
    contents. If you have 'foo.jar', that contains 'some-image.jpg', then
    it will create a folder, foo.jar, with an image inside.
    """
    expand_whitelist = ['.jar', '.xpi']
    tempdir = extract_zip(xpi)

    if expand:
        for x in xrange(0, 10):
            flag = False
            for root, dirs, files in os.walk(tempdir):
                for name in files:
                    if os.path.splitext(name)[1] in expand_whitelist:
                        src = os.path.join(root, name)
                        if not os.path.isdir(src):
                            dest = extract_zip(src, remove=True, fatal=False)
                            if dest:
                                copy_over(dest, src)
                                flag = True
            if not flag:
                break

    copy_over(tempdir, path)


def parse_xpi(xpi, addon=None):
    """Extract and parse an XPI."""
    # Extract to /tmp
    path = tempfile.mkdtemp()
    try:
        extract_xpi(xpi, path)
        rdf = Extractor.parse(path)
    except forms.ValidationError:
        raise
    except IOError as (errno, strerror):
        log.error('I/O error({0}): {1}'.format(errno, strerror))
        raise forms.ValidationError(_('Could not parse install.rdf.'))
    except Exception:
        log.error('XPI parse error', exc_info=True)
        raise forms.ValidationError(_('Could not parse install.rdf.'))
    finally:
        shutil.rmtree(path)

    return check_rdf(rdf, addon)


def check_rdf(rdf, addon=None):
    from addons.models import Addon, BlacklistedGuid
    if not rdf['guid']:
        raise forms.ValidationError(_("Could not find a UUID."))
    if addon and addon.guid != rdf['guid']:
        raise forms.ValidationError(_("UUID doesn't match add-on."))
    if (not addon
        and Addon.objects.filter(guid=rdf['guid']).exists()
        or BlacklistedGuid.objects.filter(guid=rdf['guid']).exists()):
        raise forms.ValidationError(_('Duplicate UUID found.'))
    if len(rdf['version']) > 32:
        raise forms.ValidationError(
            _('Version numbers should have fewer than 32 characters.'))
    if not VERSION_RE.match(rdf['version']):
        raise forms.ValidationError(
            _('Version numbers should only contain letters, numbers, '
              'and these punctuation characters: +*.-_.'))
    return rdf


def parse_addon(pkg, addon=None):
    """pkg is a filepath or a django.core.files.UploadedFile."""
    name = getattr(pkg, 'name', pkg)
    if name.endswith('.xml'):
        parsed = parse_search(pkg, addon)
    else:
        parsed = parse_xpi(pkg, addon)

    if addon and addon.type != parsed['type']:
        raise forms.ValidationError(
            _("<em:type> doesn't match add-on"))
    return parsed


def get_md5(filename, block_size=2 ** 20):
    """Returns an MD5 hash for a filename."""
    f = open(filename, 'rb')
    md5 = hashlib.md5()
    while True:
        data = f.read(block_size)
        if not data:
            break
        md5.update(data)
    return md5.hexdigest()


def find_jetpacks(minver, maxver):
    """
    Find all jetpack files that aren't disabled.

    Files that should be upgraded will have needs_upgrade=True.
    """
    from .models import File
    statuses = amo.VALID_STATUSES
    files = (File.objects.filter(jetpack_version__isnull=False,
                                 version__addon__status__in=statuses,
                                 version__addon__disabled_by_user=False)
             .exclude(status=amo.STATUS_DISABLED).no_cache()
             .select_related('version'))
    files = sorted(files, key=lambda f: (f.version.addon_id, f.version.id))

    # Figure out which files need to be upgraded.
    for file_ in files:
        file_.needs_upgrade = False
    # If any files for this add-on are reviewed, take the last reviewed file
    # plus all newer files.  Otherwise, only upgrade the latest file.
    for _, fs in groupby(files, key=lambda f: f.version.addon_id):
        fs = list(fs)
        if any(f.status in amo.REVIEWED_STATUSES for f in fs):
            for file_ in reversed(fs):
                file_.needs_upgrade = True
                if file_.status in amo.REVIEWED_STATUSES:
                    break
        else:
            fs[-1].needs_upgrade = True
    # Make sure only old files are marked.
    for file_ in [f for f in files if f.needs_upgrade]:
        if not (vint(minver) <= vint(file_.jetpack_version) < vint(maxver)):
            file_.needs_upgrade = False
    return files


class JetpackUpgrader(object):
    """A little manager for jetpack upgrade data in redis."""
    prefix = 'admin:jetpack:upgrade:'

    def __init__(self):
        self.redis = redisutils.connections['master']
        self.version_key = self.prefix + 'version'
        self.file_key = self.prefix + 'files'
        self.jetpack_key = self.prefix + 'jetpack'

    def jetpack_versions(self, min_=None, max_=None):
        if None not in (min_, max_):
            d = {'min': min_, 'max': max_}
            return self.redis.hmset(self.jetpack_key, d)
        d = self.redis.hgetall(self.jetpack_key) or {}
        return d.get('min'), d.get('max')

    def version(self, val=None):
        if val is not None:
            return self.redis.setnx(self.version_key, val)
        return self.redis.get(self.version_key)

    def files(self, val=None):
        if val is not None:
            for key, value in val.items():
                val[key] = pickle.dumps(value)
            return self.redis.hmset(self.file_key, val)
        response = self.redis.hgetall(self.file_key)
        return dict((key, pickle.loads(value))
                    for key, value in response.items())

    def file(self, file_id, val=None):
        if val is not None:
            return self.redis.hset(self.file_key, file_id,
                                   pickle.dumps(val))
        response = self.redis.hget(self.file_key, file_id)
        return pickle.loads(response) if response else {}

    def cancel(self):
        self.redis.delete(self.version_key)
        for key, data in self.files().items():
            if data.get('owner') == 'bulk':
                self.redis.hdel(self.file_key, key)

    def finish(self, file_id):
        self.redis.hdel(self.file_key, file_id)
        if not self.redis.hlen(self.file_key):
            self.redis.delete(self.version_key)
