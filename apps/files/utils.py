import collections
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import StringIO
import tempfile
import zipfile

from cStringIO import StringIO as cStringIO
from datetime import datetime
from itertools import groupby
from xml.dom import minidom
from zipfile import BadZipfile, ZipFile

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.utils.translation import trans_real as translation
from django.core.files.storage import default_storage as storage

import rdflib
from tower import ugettext as _

import amo
from amo.utils import rm_local_tmp_dir, strip_bom, to_language
from applications.models import AppVersion
from versions.compare import version_int as vint


log = logging.getLogger('files.utils')


class ParseError(forms.ValidationError):
    pass


VERSION_RE = re.compile('^[-+*.\w]{,32}$')
SIGNED_RE = re.compile('^META\-INF/(\w+)\.(rsa|sf)$')
# The default update URL.
default = ('https://versioncheck.addons.mozilla.org/update/VersionCheck.php?'
    'reqVersion=%REQ_VERSION%&id=%ITEM_ID%&version=%ITEM_VERSION%&'
    'maxAppVersion=%ITEM_MAXAPPVERSION%&status=%ITEM_STATUS%&appID=%APP_ID%&'
    'appVersion=%APP_VERSION%&appOS=%APP_OS%&appABI=%APP_ABI%&'
    'locale=%APP_LOCALE%&currentAppVersion=%CURRENT_APP_VERSION%&'
    'updateType=%UPDATE_TYPE%')


def get_filepath(fileorpath):
    """Get the actual file path of fileorpath if it's a FileUpload object."""
    if hasattr(fileorpath, 'path'):  # FileUpload
        return fileorpath.path
    return fileorpath


def get_file(fileorpath):
    """Get a file-like object, whether given a FileUpload object or a path."""
    if hasattr(fileorpath, 'path'):  # FileUpload
        return storage.open(fileorpath.path)
    if hasattr(fileorpath, 'name'):
        return fileorpath
    return storage.open(fileorpath)


def make_xpi(files):
    f = cStringIO()
    z = ZipFile(f, 'w')
    for path, data in files.items():
        z.writestr(path, data)
    z.close()
    f.seek(0)
    return f


class Extractor(object):
    """Extract add-on info from an install.rdf."""
    TYPES = {'2': amo.ADDON_EXTENSION, '4': amo.ADDON_THEME,
             '8': amo.ADDON_LPAPP, "64": amo.ADDON_DICT}
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
            'strict_compatibility': self.find('strictCompatibility') == 'true',
            'apps': self.apps(),
        }

    @classmethod
    def parse(cls, install_rdf):
        return cls(install_rdf).data

    def find_type(self):
        # If the extension declares a type that we know about, use
        # that.
        # FIXME: Fail if it declares a type we don't know about.
        declared_type = self.find('type')
        if declared_type and declared_type in self.TYPES:
            return self.TYPES[declared_type]

        # Look for Complete Themes.
        if self.path.endswith('.jar') or self.find('internalName'):
            return amo.ADDON_THEME

        # Look for dictionaries.
        dic = os.path.join(self.path, 'dictionaries')
        if os.path.exists(dic) and glob.glob('%s/*.dic' % dic):
            return amo.ADDON_DICT

        # Consult <em:type>.
        return self.TYPES.get(declared_type, amo.ADDON_EXTENSION)

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


def parse_search(fileorpath, addon=None):
    try:
        f = get_file(fileorpath)
        data = extract_search(f)
    except forms.ValidationError:
        raise
    except Exception:
        log.error('OpenSearch parse error', exc_info=True)
        raise forms.ValidationError(_('Could not parse uploaded file.'))

    return {'guid': None,
            'type': amo.ADDON_SEARCH,
            'name': data['name'],
            'summary': data['description'],
            'version': datetime.now().strftime('%Y%m%d')}


class WebAppParser(object):

    def extract_locale(self, locales, key, default=None):
        """Gets a locale item based on key.

        For example, given this:

            locales = {'en': {'foo': 1, 'bar': 2},
                       'it': {'foo': 1, 'bar': 2}}

        You can get english foo like:

            self.extract_locale(locales, 'foo', 'en')

        """
        ex = {}
        for loc, data in locales.iteritems():
            ex[loc] = data.get(key, default)
        return ex

    def get_json_data(self, fileorpath):
        path = get_filepath(fileorpath)
        if zipfile.is_zipfile(path):
            zf = SafeUnzip(path)
            zf.is_valid()  # Raises forms.ValidationError if problems.
            try:
                data = zf.extract_path('manifest.webapp')
            except KeyError:
                raise forms.ValidationError(
                    _('The file "manifest.webapp" was not found at the root '
                      'of the packaged app archive.'))
        else:
            file_ = get_file(fileorpath)
            data = file_.read()
            file_.close()

        return WebAppParser.decode_manifest(data)

    @classmethod
    def decode_manifest(cls, manifest):
        """
        Returns manifest, stripped of BOMs and UTF-8 decoded, as Python dict.
        """
        try:
            data = strip_bom(manifest)
            # Marketplace only supports UTF-8 encoded manifests.
            decoded_data = data.decode('utf-8')
        except (ValueError, UnicodeDecodeError) as exc:
            msg = 'Error parsing manifest (encoding: utf-8): %s: %s'
            log.error(msg % (exc.__class__.__name__, exc))
            raise forms.ValidationError(
                _('Could not decode the webapp manifest file.'))

        try:
            return json.loads(decoded_data)
        except Exception:
            raise forms.ValidationError(
                _('The webapp manifest is not valid JSON.'))

    def parse(self, fileorpath):
        data = self.get_json_data(fileorpath)
        loc = data.get('default_locale', translation.get_language())
        default_locale = self.trans_locale(loc)
        locales = data.get('locales', {})
        if type(locales) == list:
            raise forms.ValidationError(
                _('Your specified app locales are not in the correct format.'))

        localized_descr = self.extract_locale(locales, 'description',
                                              default='')
        if 'description' in data:
            localized_descr.update({default_locale: data['description']})

        localized_name = self.extract_locale(locales, 'name',
                                             default=data['name'])
        localized_name.update({default_locale: data['name']})

        developer_info = data.get('developer', {})
        developer_name = developer_info.get('name')
        if not developer_name:
            # Missing developer name shouldn't happen if validation took place,
            # but let's be explicit about this just in case.
            raise forms.ValidationError(
                _("Developer name is required in the manifest in order to "
                  "display it on the app's listing."))

        return {'guid': None,
                'type': amo.ADDON_WEBAPP,
                'name': self.trans_all_locales(localized_name),
                'developer_name': developer_name,
                'description': self.trans_all_locales(localized_descr),
                'version': data.get('version', '1.0'),
                'default_locale': default_locale,
                'origin': data.get('origin')}

    def trans_locale(self, locale):
        return to_language(settings.SHORTER_LANGUAGES.get(locale, locale))

    def trans_all_locales(self, locale_dict):
        trans = {}
        for key, item in locale_dict.iteritems():
            key = self.trans_locale(key)
            trans[key] = item
        return trans


class SafeUnzip(object):
    def __init__(self, source, mode='r'):
        self.source = source
        self.info = None
        self.mode = mode

    def is_valid(self, fatal=True):
        """
        Runs some overall archive checks.
        fatal: if the archive is not valid and fatal is True, it will raise
               an error, otherwise it will return False.
        """
        try:
            zip = zipfile.ZipFile(self.source, self.mode)
        except (BadZipfile, IOError):
            if fatal:
                log.info('Error extracting', exc_info=True)
                raise
            return False

        _info = zip.infolist()

        for info in _info:
            if '..' in info.filename or info.filename.startswith('/'):
                log.error('Extraction error, invalid file name (%s) in '
                          'archive: %s' % (info.filename, self.source))
                # L10n: {0} is the name of the invalid file.
                raise forms.ValidationError(
                    _('Invalid file name in archive: {0}').format(
                        info.filename))

            if info.file_size > settings.FILE_UNZIP_SIZE_LIMIT:
                log.error('Extraction error, file too big (%s) for file (%s): '
                          '%s' % (self.source, info.filename, info.file_size))
                # L10n: {0} is the name of the invalid file.
                raise forms.ValidationError(
                    _('File exceeding size limit in archive: {0}').format(
                        info.filename))

        self.info = _info
        self.zip = zip
        return True

    def is_signed(self):
        """Tells us if an addon is signed."""
        finds = []
        for info in self.info:
            match = SIGNED_RE.match(info.filename)
            if match:
                name, ext = match.groups()
                # If it's rsa or sf, just look for the opposite.
                if (name, {'rsa': 'sf', 'sf': 'rsa'}[ext]) in finds:
                    return True
                finds.append((name, ext))

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

    def close(self):
        self.zip.close()


def extract_zip(source, remove=False, fatal=True):
    """Extracts the zip file. If remove is given, removes the source file."""
    tempdir = tempfile.mkdtemp()

    zip = SafeUnzip(source)
    try:
        if zip.is_valid(fatal):
            zip.extract_to_dest(tempdir)
    except:
        rm_local_tmp_dir(tempdir)
        raise

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
        xpi = get_file(xpi)
        extract_xpi(xpi, path)
        rdf = Extractor.parse(path)
    except forms.ValidationError:
        raise
    except IOError as e:
        if len(e.args) < 2:
            errno, strerror = None, e[0]
        else:
            errno, strerror = e
        log.error('I/O error({0}): {1}'.format(errno, strerror))
        raise forms.ValidationError(_('Could not parse install.rdf.'))
    except Exception:
        log.error('XPI parse error', exc_info=True)
        raise forms.ValidationError(_('Could not parse install.rdf.'))
    finally:
        rm_local_tmp_dir(path)

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
    """
    pkg is a filepath or a django.core.files.UploadedFile
    or files.models.FileUpload.
    """
    name = getattr(pkg, 'name', pkg)
    if (getattr(pkg, 'is_webapp', False) or
        name.endswith(('.webapp', '.json', '.zip'))):
        parsed = WebAppParser().parse(pkg)
    elif name.endswith('.xml'):
        parsed = parse_search(pkg, addon)
    else:
        parsed = parse_xpi(pkg, addon)

    if addon and addon.type != parsed['type']:
        raise forms.ValidationError(_("<em:type> doesn't match add-on"))
    return parsed


def _get_hash(filename, block_size=2 ** 20, hash=hashlib.md5):
    """Returns an MD5 hash for a filename."""
    f = open(filename, 'rb')
    hash_ = hash()
    while True:
        data = f.read(block_size)
        if not data:
            break
        hash_.update(data)
    return hash_.hexdigest()


def get_md5(filename, **kw):
    return _get_hash(filename, **kw)


def get_sha256(filename, **kw):
    return _get_hash(filename, hash=hashlib.sha256, **kw)


def find_jetpacks(minver, maxver, from_builder_only=False):
    """
    Find all jetpack files that aren't disabled.

    Files that should be upgraded will have needs_upgrade=True.

    Keyword Args

    from_builder_only=False
        If True, the jetpacks returned are only those that were created
        and packaged by the builder.
    """
    from .models import File
    statuses = amo.VALID_STATUSES
    files = (File.objects.filter(jetpack_version__isnull=False,
                                 version__addon__auto_repackage=True,
                                 version__addon__status__in=statuses,
                                 version__addon__disabled_by_user=False)
             .exclude(status=amo.STATUS_DISABLED).no_cache()
             .select_related('version'))
    if from_builder_only:
        files = files.exclude(builder_version=None)
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
    """A little manager for jetpack upgrade data in memcache."""
    prefix = 'admin:jetpack:upgrade:'

    def __init__(self):
        self.version_key = self.prefix + 'version'
        self.file_key = self.prefix + 'files'
        self.jetpack_key = self.prefix + 'jetpack'

    def jetpack_versions(self, min_=None, max_=None):
        if None not in (min_, max_):
            d = {'min': min_, 'max': max_}
            return cache.set(self.jetpack_key, d)
        d = cache.get(self.jetpack_key, {})
        return d.get('min'), d.get('max')

    def version(self, val=None):
        if val is not None:
            return cache.add(self.version_key, val)
        return cache.get(self.version_key)

    def files(self, val=None):
        if val is not None:
            current = cache.get(self.file_key, {})
            current.update(val)
            return cache.set(self.file_key, val)
        return cache.get(self.file_key, {})

    def file(self, file_id, val=None):
        file_id = int(file_id)
        if val is not None:
            current = cache.get(self.file_key, {})
            current[file_id] = val
            cache.set(self.file_key, current)
            return val
        return cache.get(self.file_key, {}).get(file_id, {})

    def cancel(self):
        cache.delete(self.version_key)
        newfiles = dict([(k, v) for (k, v) in self.files().items()
                         if v.get('owner') != 'bulk'])
        cache.set(self.file_key, newfiles)

    def finish(self, file_id):
        file_id = int(file_id)
        newfiles = dict([(k, v) for (k, v) in self.files().items()
                         if k != file_id])
        cache.set(self.file_key, newfiles)
        if not newfiles:
            cache.delete(self.version_key)
