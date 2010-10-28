import collections
import hashlib
import os
import shutil
import time
import zipfile
from xml.dom.minidom import parse

from django import forms
from django.conf import settings

import commonware.log
from tower import ugettext as _
import happyforms

import amo
from addons.models import Addon, AddonUser
from files.models import File
from versions.models import ApplicationsVersions, AppVersion, Version

license_ids = dict((license.shortname, license.id) for license in amo.LICENSES)

log = commonware.log.getLogger('z.addons')


def get_text_value(xml, tag):
    node = xml.getElementsByTagName('em:%s' % tag)[0]
    if node.childNodes:
        textnode = node.childNodes[0]
        return textnode.wholeText


def parse_xpi(xpi, addon=None):
    # Extract to /tmp
    path = os.path.join(settings.TMP_PATH, str(time.time()))
    os.makedirs(path)

    # Validating that we have no member files that try to break out of
    # the destination path.  NOTE: This will be obsolete when this bug is
    # fixed: http://bugs.python.org/issue6972
    zip = zipfile.ZipFile(xpi)

    for f in zip.namelist():
        if '..' in f or f.startswith('/'):
            raise forms.ValidationError(_('Invalid archive.'))

    zip.extractall(path)

    # read RDF and store in clean_data
    rdf = parse(os.path.join(path, 'install.rdf'))
    # XPIs use their own type ids
    XPI_TYPES = {'2': amo.ADDON_EXTENSION, '4': amo.ADDON_THEME,
                 '8': amo.ADDON_LPADDON}

    apps = []
    App = collections.namedtuple('App', 'appdata id min max')
    for node in rdf.getElementsByTagName('em:targetApplication'):
        app = amo.APP_GUIDS.get(get_text_value(node, 'id'))
        min_val = get_text_value(node, 'minVersion')
        max_val = get_text_value(node, 'maxVersion')

        try:
            min = AppVersion.objects.get(application=app.id,
                                         version=min_val)
            max = AppVersion.objects.get(application=app.id,
                                         version=max_val)
        except AppVersion.DoesNotExist:
            continue

        if app:
            apps.append(App(appdata=app, id=app.id, min=min, max=max))

    guid = get_text_value(rdf, 'id')

    if addon and addon.guid != guid:
        raise forms.ValidationError(_("GUID doesn't match add-on"))
    if not addon and Addon.objects.filter(guid=guid):
        raise forms.ValidationError(_('Duplicate GUID found.'))

    shutil.rmtree(path)

    return dict(
                guid=guid,
                name=get_text_value(rdf, 'name'),
                description=get_text_value(rdf, 'description'),
                version=get_text_value(rdf, 'version'),
                homepage=get_text_value(rdf, 'homepageURL'),
                type=XPI_TYPES.get(get_text_value(rdf, 'type')),
                apps=apps,
           )


class XPIForm(happyforms.Form):
    """
    Validates a new XPI.
    * Checks for duplicate GUID
    """

    platform = forms.ChoiceField(
                choices=[(p.shortname, p.name) for p in amo.PLATFORMS.values()
                         if p != amo.PLATFORM_ANY], required=False,)
    release_notes = forms.CharField(required=False)
    xpi = forms.FileField(required=True)

    def __init__(self, data, files, addon=None, version=None):
        self.addon = addon

        if version:
            self.version = version
            self.addon = version.addon

        super(XPIForm, self).__init__(data, files)

    def clean_platform(self):
        return self.cleaned_data['platform'] or amo.PLATFORM_ALL.shortname

    def clean_xpi(self):
        # TODO(basta): connect to addon validator.
        xpi = self.cleaned_data['xpi']
        self.cleaned_data.update(parse_xpi(xpi, self.addon))
        return xpi

    def create_addon(self, user, license=None):
        data = self.cleaned_data
        a = Addon(guid=data['guid'],
                  name=data['name'],
                  type=data['type'],
                  status=amo.STATUS_UNREVIEWED,
                  homepage=data['homepage'],
                  description=data['description'])
        a.save()
        AddonUser(addon=a, user=user).save()

        self.addon = a
        # Save Version, attach License
        self.create_version(license=license)
        log.info('Addon %d saved' % a.id)
        return a

    def _save_file(self, version):
        data = self.cleaned_data
        xpi = data['xpi']
        hash = hashlib.sha256()
        path = os.path.join(settings.ADDONS_PATH, str(version.addon.id))
        if not os.path.exists(path):
            os.mkdir(path)

        f = File(version=version,
                 platform_id=amo.PLATFORM_DICT[data['platform']].id,
                 size=xpi.size)

        filename = f.generate_filename()

        with open(os.path.join(path, filename), 'w') as destination:
            for chunk in xpi.chunks():
                hash.update(chunk)
                destination.write(chunk)

        f.hash = 'sha256:%s' % hash.hexdigest()
        f.save()
        return f

    def _save_apps(self, version):
        # clear old app versions
        version.apps.all().delete()
        apps = self.cleaned_data['apps']

        for app in apps:
            ApplicationsVersions(version=version, min=app.min, max=app.max,
                                 application_id=app.id).save()

    def create_version(self, license=None):
        data = self.cleaned_data
        v = Version(addon=self.addon, license=license,
                    version=data['version'],
                    releasenotes=data['release_notes'])
        v.save()
        self._save_apps(v)
        self._save_file(v)
        return v

    def update_version(self, license=None):
        data = self.cleaned_data
        v = self.version
        v.license = license
        v.version = data['version']
        v.releasenotes = data['release_notes']
        v.save()
        self._save_apps(v)
        self._save_file(v)
        return v


class CompatabilityForm(happyforms.Form):
    application = forms.ChoiceField(required=True,
            choices=[(a.short, a.short) for a in amo.APP_USAGE])
    min = forms.CharField(required=True)
    max = forms.CharField(required=True)

    def __init__(self, data, files=None, version=None):
        self.version = version
        super(CompatabilityForm, self).__init__(data, files)

    def clean(self):
        """Check that the version makes sense and min < max."""
        data = self.cleaned_data
        if self.errors:
            return data

        app = amo.APPS[data['application']]
        min = AppVersion.objects.filter(application=app.id,
                                        version=data['min'])
        if not min:
            raise forms.ValidationError(
                    _('{app} has no {version} version').format(
                        app=app.pretty, version=data['min']))
        min = min[0]

        max = AppVersion.objects.filter(application=app.id,
                                        version=data['max'])

        if not max:
            raise forms.ValidationError(
                    _('{app} has no {version} version').format(
                        app=app.pretty, version=data['max']))

        max = max[0]

        if min.version_int > max.version_int:
            raise forms.ValidationError(
                    _('Minimum version is greater than '
                      'maximum supported version.'))

        return(dict(app=app, min=min, max=max))

    def save(self):
        if not self.version:
            return

        data = self.cleaned_data

        # check existing AVs
        try:
            c = self.version.apps.get(application=data['app'].id)
        except ApplicationsVersions.DoesNotExist:
            c = ApplicationsVersions(application_id=data['app'].id,
                                     version=self.version)

        c.min = data['min']
        c.max = data['max']
        c.save()
        return c
