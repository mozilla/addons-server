import collections
import logging
import os
import shutil
import time
import unicodedata
import zipfile
from datetime import datetime
from xml.dom import minidom

from django import forms
from django.conf import settings

import rdflib
from tower import ugettext as _

import amo
from applications.models import AppVersion

log = logging.getLogger('files.utils')


class ParseError(forms.ValidationError):
    pass


class Extractor(object):
    """Extract add-on info from an install.rdf."""
    TYPES = {'2': amo.ADDON_EXTENSION, '4': amo.ADDON_THEME,
             '8': amo.ADDON_LPADDON}
    App = collections.namedtuple('App', 'appdata id min max')
    manifest = u'urn:mozilla:install-manifest'

    def __init__(self, install_rdf):
        self.rdf = rdflib.Graph().parse(open(install_rdf))
        self.find_root()
        self.data = {
            'guid': self.find('id'),
            'type': self.TYPES.get(self.find('type'), amo.ADDON_EXTENSION),
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


def parse_xpi(xpi, addon=None):
    """Extract and parse an XPI."""
    from addons.models import Addon
    # Extract to /tmp
    path = os.path.join(settings.TMP_PATH, str(time.time()))
    os.makedirs(path)
    try:
        zip = zipfile.ZipFile(xpi)
        for f in zip.namelist():
            if '..' in f or f.startswith('/'):
                raise forms.ValidationError(_('Invalid archive.'))
        zip.extractall(path)
        rdf = Extractor.parse(os.path.join(path, 'install.rdf'))
    except forms.ValidationError:
        raise
    except Exception:
        log.error('XPI parse error', exc_info=True)
        raise forms.ValidationError(_('Could not parse install.rdf.'))
    finally:
        shutil.rmtree(path)

    if addon and addon.guid != rdf['guid']:
        raise forms.ValidationError(_("UUID doesn't match add-on"))
    if not addon and Addon.objects.filter(guid=rdf['guid']):
        raise forms.ValidationError(_('Duplicate UUID found.'))

    if addon and addon.type != rdf['type']:
        raise forms.ValidationError(
            _("<em:type> doesn't match add-on"))
    return rdf


def parse_addon(pkg, addon=None):
    """pkg is a filepath or a django.core.files.UploadedFile."""
    name = getattr(pkg, 'name', pkg)
    if name.endswith('.xml'):
        return parse_search(pkg, addon)
    else:
        return parse_xpi(pkg, addon)


def nfd_str(u):
    """Uses NFD to normalize unicode strings."""
    if isinstance(u, unicode):
        return unicodedata.normalize('NFD', u).encode('utf-8')
    return u
