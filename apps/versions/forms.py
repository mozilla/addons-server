import hashlib
import os

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage as storage

import commonware.log
import happyforms

import amo
from addons.models import Addon, AddonUser
from files.models import File
from files.utils import parse_addon
from versions.models import ApplicationsVersions, Version

log = commonware.log.getLogger('z.addons')


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

    def __init__(self, request, data, files, addon=None, version=None):
        self.addon = addon
        self.request = request

        if version:
            self.version = version
            self.addon = version.addon

        super(XPIForm, self).__init__(data, files)

    def clean_platform(self):
        return self.cleaned_data['platform'] or amo.PLATFORM_ALL.shortname

    def clean_xpi(self):
        # TODO(basta): connect to addon validator.
        xpi = self.cleaned_data['xpi']
        self.cleaned_data.update(parse_addon(xpi, self.addon))
        return xpi

    def create_addon(self, license=None):
        data = self.cleaned_data
        a = Addon(guid=data['guid'],
                  name=data['name'],
                  type=data['type'],
                  status=amo.STATUS_UNREVIEWED,
                  homepage=data['homepage'],
                  summary=data['summary'])
        a.save()
        AddonUser(addon=a, user=self.request.amo_user).save()

        self.addon = a
        # Save Version, attach License
        self.create_version(license=license)
        amo.log(amo.LOG.CREATE_ADDON, a)
        log.info('Addon %d saved' % a.id)
        return a

    def _save_file(self, version):
        data = self.cleaned_data
        xpi = data['xpi']
        hash = hashlib.sha256()

        f = File(version=version,
                 platform_id=amo.PLATFORM_DICT[data['platform']].id,
                 size=xpi.size)

        filename = f.generate_filename()
        path = os.path.join(settings.ADDONS_PATH, str(version.addon.id))
        with storage.open(os.path.join(path, filename), 'wb') as destination:
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
            av = ApplicationsVersions.objects.create(version=version,
                    min=app.min, max=app.max, application_id=app.id)
            amo.log(amo.LOG.ADD_APPVERSION,
                    version, version.addon, app.appdata.short, av)

    def create_version(self, license=None):
        data = self.cleaned_data
        v = Version(addon=self.addon, license=license,
                    version=data['version'],
                    releasenotes=data['release_notes'])
        v.save()
        amo.log(amo.LOG.ADD_VERSION, v.addon, v)
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
        amo.log(amo.LOG.EDIT_VERSION, v.addon, v)
        self._save_apps(v)
        self._save_file(v)
        return v
