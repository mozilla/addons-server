import collections
import contextlib
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
from django.core.files.storage import default_storage as storage

import rdflib
import waffle
from lxml import etree
from tower import ugettext as _

from olympia import amo
from olympia.amo.utils import rm_local_tmp_dir
from olympia.applications.models import AppVersion
from olympia.versions.compare import version_int as vint


log = logging.getLogger('z.files.utils')


class ParseError(forms.ValidationError):
    pass


VERSION_RE = re.compile('^[-+*.\w]{,32}$')
SIGNED_RE = re.compile('^META\-INF/(\w+)\.(rsa|sf)$')
# The default update URL.
default = (
    'https://versioncheck.addons.mozilla.org/update/VersionCheck.php?'
    'reqVersion=%REQ_VERSION%&id=%ITEM_ID%&version=%ITEM_VERSION%&'
    'maxAppVersion=%ITEM_MAXAPPVERSION%&status=%ITEM_STATUS%&appID=%APP_ID%&'
    'appVersion=%APP_VERSION%&appOS=%APP_OS%&appABI=%APP_ABI%&'
    'locale=%APP_LOCALE%&currentAppVersion=%CURRENT_APP_VERSION%&'
    'updateType=%UPDATE_TYPE%'
)


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


def is_beta(version):
    """Return True if the version is believed to be a beta version."""
    return bool(amo.VERSION_BETA.search(version))


class Extractor(object):
    """Extract adon info from an install.rdf or package.json"""
    App = collections.namedtuple('App', 'appdata id min max')

    @classmethod
    def parse(cls, path):
        install_rdf = os.path.join(path, 'install.rdf')
        package_json = os.path.join(path, 'package.json')
        manifest_json = os.path.join(path, 'manifest.json')
        if os.path.exists(install_rdf):
            return RDFExtractor(path).data
        elif os.path.exists(package_json):
            return PackageJSONExtractor(package_json).parse()
        elif os.path.exists(manifest_json):
            if waffle.switch_is_active('webextensions'):
                return ManifestJSONExtractor(manifest_json).parse()
            else:
                raise forms.ValidationError("WebExtensions aren't allowed yet")
        else:
            raise forms.ValidationError(
                "No install.rdf or package.json or manifest.json found")


def get_appversions(app, min_version, max_version):
    """Return the `AppVersion`s that correspond to the given versions."""
    qs = AppVersion.objects.filter(application=app.id)
    min_appver = qs.get(version=min_version)
    max_appver = qs.get(version=max_version)
    return min_appver, max_appver


def get_simple_version(version_string):
    """Extract the version number without the ><= requirements.

    This simply extracts the version number without the ><= requirement so
    it will not be accurate for version requirements that are not >=, <= or
    = to a version.

    >>> get_simple_version('>=33.0a1')
    '33.0a1'
    """
    if not version_string:
        return ''
    return re.sub('[<=>]', '', version_string)


class JSONExtractor(object):
    def __init__(self, path, data=''):
        self.path = path
        self.data = json.loads(data) if data else json.load(open(self.path))

    def get(self, key, default=None):
        return self.data.get(key, default)


class PackageJSONExtractor(JSONExtractor):

    def find_appversion(self, app, version_req):
        """
        Convert an app and a package.json style version requirement to an
        `AppVersion`.
        """
        version = get_simple_version(version_req)
        try:
            return AppVersion.objects.get(
                application=app.id, version=version)
        except AppVersion.DoesNotExist:
            return None

    def apps(self):
        for engine, version in self.get('engines', {}).items():
            name = 'android' if engine == 'fennec' else engine
            app = amo.APPS.get(name)
            if app and app.guid in amo.APP_GUIDS:
                version = get_simple_version(version)
                try:
                    min_appver, max_appver = get_appversions(app, version,
                                                             version)
                except:
                    continue
                yield Extractor.App(
                    appdata=app, id=app.id, min=min_appver, max=max_appver)

    def parse(self):
        return {
            'guid': self.get('id') or self.get('name'),
            'type': amo.ADDON_EXTENSION,
            'name': self.get('title') or self.get('name'),
            'version': self.get('version'),
            'homepage': self.get('homepage'),
            'summary': self.get('description'),
            'no_restart': True,
            'apps': list(self.apps()),
        }


class RDFExtractor(object):
    """Extract add-on info from an install.rdf."""
    EXPERIMENT_TYPE = '128'  # Experiment extensions: bug 1220097.
    TYPES = {'2': amo.ADDON_EXTENSION, '4': amo.ADDON_THEME,
             '8': amo.ADDON_LPAPP, '64': amo.ADDON_DICT,
             EXPERIMENT_TYPE: amo.ADDON_EXTENSION}
    manifest = u'urn:mozilla:install-manifest'
    is_experiment = False  # Experiment extensions: bug 1220097.

    def __init__(self, path):
        self.path = path
        install_rdf_path = os.path.join(path, 'install.rdf')
        self.rdf = rdflib.Graph().parse(open(install_rdf_path))
        self.package_type = None
        self.find_root()
        self.data = {
            'guid': self.find('id'),
            'type': self.find_type(),
            'name': self.find('name'),
            'version': self.find('version'),
            'homepage': self.find('homepageURL'),
            'summary': self.find('description'),
            'no_restart':
                self.find('bootstrap') == 'true' or self.find('type') == '64',
            'strict_compatibility': self.find('strictCompatibility') == 'true',
            'apps': self.apps(),
            'is_multi_package': self.package_type == '32',
        }
        # `experiment` is detected in in `find_type`.
        self.data['is_experiment'] = self.is_experiment

    def find_type(self):
        # If the extension declares a type that we know about, use
        # that.
        # https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#type
        self.package_type = self.find('type')
        if self.package_type and self.package_type in self.TYPES:
            # If it's an experiment, we need to store that for later.
            self.is_experiment = self.package_type == self.EXPERIMENT_TYPE
            return self.TYPES[self.package_type]

        # Look for Complete Themes.
        if self.path.endswith('.jar') or self.find('internalName'):
            return amo.ADDON_THEME

        # Look for dictionaries.
        dic = os.path.join(self.path, 'dictionaries')
        if os.path.exists(dic) and glob.glob('%s/*.dic' % dic):
            return amo.ADDON_DICT

        # Consult <em:type>.
        return self.TYPES.get(self.package_type, amo.ADDON_EXTENSION)

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
            if app.guid not in amo.APP_GUIDS:
                continue
            try:
                min_appver, max_appver = get_appversions(
                    app,
                    self.find('minVersion', ctx),
                    self.find('maxVersion', ctx))
            except AppVersion.DoesNotExist:
                continue
            rv.append(Extractor.App(
                appdata=app, id=app.id, min=min_appver, max=max_appver))
        return rv


class ManifestJSONExtractor(JSONExtractor):

    @property
    def gecko(self):
        """Return the "applications["gecko"]" part of the manifest."""
        return self.get('applications', {}).get('gecko', {})

    @property
    def app(self):
        """Get `AppVersion`s for the application."""
        if not self.gecko:
            return
        app = amo.FIREFOX
        strict_min_version = (
            # At least this version supports installing.
            get_simple_version(self.gecko.get('strict_min_version')) or '42.0')
        strict_max_version = (
            # Not sure what we should default to here.
            get_simple_version(self.gecko.get('strict_max_version')) or '42.*')
        try:
            min_appver, max_appver = get_appversions(
                app, strict_min_version, strict_max_version)
        except AppVersion.DoesNotExist:
            return
        return Extractor.App(appdata=app, id=app.id, min=min_appver,
                             max=max_appver)

    def parse(self):
        return {
            'guid': self.gecko.get('id', {}) or self.get('name'),
            'type': amo.ADDON_EXTENSION,
            'name': self.get('name'),
            'version': self.get('version'),
            'homepage': self.get('homepage_url'),
            'summary': self.get('description'),
            'no_restart': True,
            'apps': [self.app] if self.app else [],
            'is_webextension': True,
        }


def extract_search(content):
    rv = {}
    dom = minidom.parse(content)

    def text(x):
        return dom.getElementsByTagName(x)[0].childNodes[0].wholeText

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


class SafeUnzip(object):
    def __init__(self, source, mode='r'):
        self.source = source
        self.info_list = None
        self.mode = mode

    def is_valid(self, fatal=True):
        """
        Runs some overall archive checks.
        fatal: if the archive is not valid and fatal is True, it will raise
               an error, otherwise it will return False.
        """
        try:
            zip_file = zipfile.ZipFile(self.source, self.mode)
        except (BadZipfile, IOError):
            log.info('Error extracting %s', self.source, exc_info=True)
            if fatal:
                raise
            return False

        info_list = zip_file.infolist()

        for info in info_list:
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

        self.info_list = info_list
        self.zip_file = zip_file
        return True

    def is_signed(self):
        """Tells us if an addon is signed."""
        finds = []
        for info in self.info_list:
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
                jar = self.__class__(
                    StringIO.StringIO(jar.zip_file.read(part)))
                jar.is_valid(fatal=True)
            path = parts[-1]
        return jar.extract_path(path[1:] if path.startswith('/') else path)

    def extract_path(self, path):
        """Given a path, extracts the content at path."""
        return self.zip_file.read(path)

    def extract_info_to_dest(self, info, dest):
        """Extracts the given info to a directory and checks the file size."""
        self.zip_file.extract(info, dest)
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
        for info in self.info_list:
            self.extract_info_to_dest(info, dest)

    def close(self):
        self.zip_file.close()


def extract_zip(source, remove=False, fatal=True):
    """Extracts the zip file. If remove is given, removes the source file."""
    tempdir = tempfile.mkdtemp()

    zip_file = SafeUnzip(source)
    try:
        if zip_file.is_valid(fatal):
            zip_file.extract_to_dest(tempdir)
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
    # mkdtemp will set the directory permissions to 700
    # for the webserver to read them, we need 755
    os.chmod(dest, stat.S_IRWXU | stat.S_IRGRP |
             stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
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


def parse_xpi(xpi, addon=None, check=True):
    """Extract and parse an XPI."""
    # Extract to /tmp
    path = tempfile.mkdtemp()
    try:
        xpi = get_file(xpi)
        extract_xpi(xpi, path)
        xpi_info = Extractor.parse(path)
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

    if check:
        return check_xpi_info(xpi_info, addon)
    else:
        return xpi_info


def check_xpi_info(xpi_info, addon=None):
    from addons.models import Addon, BlacklistedGuid
    guid = xpi_info['guid']
    if not guid:
        raise forms.ValidationError(_("Could not find an add-on ID."))
    if not waffle.switch_is_active('allow-long-addon-guid') and len(guid) > 64:
        raise forms.ValidationError(
            _("Add-on ID must be 64 characters or less."))
    if addon and addon.guid != guid:
        raise forms.ValidationError(_("Add-on ID doesn't match add-on."))
    if (not addon and
            (Addon.with_unlisted.filter(guid=guid).exists()
             or BlacklistedGuid.objects.filter(guid=guid).exists())):
        raise forms.ValidationError(_('Duplicate add-on ID found.'))
    if len(xpi_info['version']) > 32:
        raise forms.ValidationError(
            _('Version numbers should have fewer than 32 characters.'))
    if not VERSION_RE.match(xpi_info['version']):
        raise forms.ValidationError(
            _('Version numbers should only contain letters, numbers, '
              'and these punctuation characters: +*.-_.'))
    return xpi_info


def parse_addon(pkg, addon=None, check=True):
    """
    pkg is a filepath or a django.core.files.UploadedFile
    or files.models.FileUpload.
    """
    name = getattr(pkg, 'name', pkg)
    if name.endswith('.xml'):
        parsed = parse_search(pkg, addon)
    else:
        parsed = parse_xpi(pkg, addon, check)

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


def find_jetpacks(minver, maxver):
    """
    Find all jetpack files that aren't disabled.

    Files that should be upgraded will have needs_upgrade=True.
    """
    from .models import File
    statuses = amo.VALID_STATUSES
    files = (File.objects.filter(jetpack_version__isnull=False,
                                 version__addon__auto_repackage=True,
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
    for _group, fs in groupby(files, key=lambda f: f.version.addon_id):
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


def zip_folder_content(folder, filename):
    """Compress the _content_ of a folder."""
    with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as dest:
        # Add each file/folder from the folder to the zip file.
        for root, dirs, files in os.walk(folder):
            relative_dir = os.path.relpath(root, folder)
            for file_ in files:
                dest.write(os.path.join(root, file_),
                           # We want the relative paths for the files.
                           arcname=os.path.join(relative_dir, file_))


@contextlib.contextmanager
def repack(xpi_path, raise_on_failure=True):
    """Unpack the XPI, yield the temp folder, and repack on exit.

    Usage:
        with repack('foo.xpi') as temp_folder:
            # 'foo.xpi' files are extracted to the temp_folder.
            modify_files(temp_folder)  # Modify the files in the temp_folder.
        # The 'foo.xpi' extension is now repacked, with the file changes.
    """
    # Unpack.
    tempdir = extract_zip(xpi_path, remove=False, fatal=raise_on_failure)
    yield tempdir
    try:
        # Repack.
        repacked = u'{0}.repacked'.format(xpi_path)  # Temporary file.
        zip_folder_content(tempdir, repacked)
        # Overwrite the initial file with the repacked one.
        shutil.move(repacked, xpi_path)
    finally:
        rm_local_tmp_dir(tempdir)


def update_version_number(file_obj, new_version_number):
    """Update the manifest to have the new version number."""
    # Create a new xpi with the updated version.
    updated = u'{0}.updated_version_number'.format(file_obj.file_path)
    # Copy the original XPI, with the updated install.rdf or package.json.
    with zipfile.ZipFile(file_obj.file_path, 'r') as source:
        file_list = source.infolist()
        with zipfile.ZipFile(updated, 'w', zipfile.ZIP_DEFLATED) as dest:
            for file_ in file_list:
                content = source.read(file_.filename)
                if file_.filename == 'install.rdf':
                    content = _update_version_in_install_rdf(
                        content, new_version_number)
                if file_.filename == 'package.json':
                    content = _update_version_in_package_json(
                        content, new_version_number)
                dest.writestr(file_, content)
    # Move the updated file to the original file.
    shutil.move(updated, file_obj.file_path)


def _update_version_in_install_rdf(content, new_version_number):
    """Change the version number in the install.rdf provided."""
    # We need to use an XML parser, and not a RDF parser, because our
    # install.rdf files aren't really standard (they use default namespaces,
    # don't namespace the "about" attribute... rdflib can parse them, and can
    # now even serialize them, but the end result could be very different from
    # the format we need.
    tree = etree.fromstring(content)
    # There's two different formats for the install.rdf: the "standard" one
    # uses nodes for each item (like <em:version>1.2</em:version>), the other
    # alternate one sets attributes on the <RDF:Description
    # RDF:about="urn:mozilla:install-manifest"> element.

    # Get the version node, if it's the common format, or the Description node
    # that has the "em:version" attribute if it's the alternate format.
    namespace = 'http://www.mozilla.org/2004/em-rdf#'
    version_uri = '{{{0}}}version'.format(namespace)
    for node in tree.xpath('//em:version | //*[@em:version]',
                           namespaces={'em': namespace}):
        if node.tag == version_uri:  # Common format, version is a node.
            node.text = new_version_number
        else:  # Alternate format, version is an attribute.
            node.set(version_uri, new_version_number)
    return etree.tostring(tree, xml_declaration=True, encoding='utf-8')


def _update_version_in_package_json(content, new_version_number):
    """Change the version number in the package.json provided."""
    updated = json.loads(content)
    if 'version' in updated:
        updated['version'] = new_version_number
    return json.dumps(updated)
