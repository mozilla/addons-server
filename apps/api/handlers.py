import functools

from django.db import transaction
from django import forms

import commonware.log
from piston.handler import AnonymousBaseHandler, BaseHandler
from piston.utils import rc, throttle
from tower import ugettext as _

import amo
from access import acl
from addons.forms import AddonForm
from addons.models import Addon
from devhub.forms import LicenseForm, CompatFormSet
from users.models import UserProfile
from versions.forms import XPIForm
from versions.models import Version, ApplicationsVersions

log = commonware.log.getLogger('z.api')


def check_addon_and_version(f):
    """
    Decorator that checks that an addon, and version exist and belong to the
    request user.
    """
    @functools.wraps(f)
    def wrapper(*args, **kw):
        request = args[1]
        version_id = kw.get('version_id')
        addon_id = kw.get('addon_id')
        if version_id:
            try:
                version = Version.objects.get(addon=addon_id, pk=version_id)
                addon = version.addon
            except Version.DoesNotExist:
                return rc.NOT_HERE

            if not acl.check_ownership(request, addon):
                return rc.FORBIDDEN

            return f(*args, addon=addon, version=version)

        elif addon_id:
            try:
                addon = Addon.objects.get(pk=addon_id)
            except:
                return rc.NOT_HERE

            if not acl.check_ownership(request, addon):
                return rc.FORBIDDEN

            return f(*args, addon=addon)

    return wrapper


def _form_error(f):
    resp = rc.BAD_REQUEST
    error = ','.join(['%s (%s)' % (v[0], k) for k, v in f.errors.iteritems()])
    resp.write(': ' +
               # L10n: {0} is comma separated data errors.
               _(u'Invalid data provided: {0}').format(error))
    log.debug(error)
    return resp


def _xpi_form_error(f, request):
    resp = rc.BAD_REQUEST
    error = ','.join([e[0] for e in f.errors.values()])
    resp.write(': ' + _('Add-on did not validate: %s') % error)
    log.debug('Add-on did not validate (%s) for %s'
              % (error, request.amo_user))
    return resp


class UserHandler(BaseHandler):
    allowed_methods = ('GET',)
    model = UserProfile
    fields = ('email',)

    def read(self, request):
        return request.amo_user


class AddonsHandler(BaseHandler):
    allowed_methods = ('POST', 'PUT', 'DELETE',)
    model = Addon
    fields = ('id', 'name', 'eula', 'guid', 'current_version',)
    exclude = ('highest_status', 'icon_type')

    # Custom handler so translated text doesn't look weird
    @classmethod
    def name(cls, addon):
        return addon.name.localized_string

    # We need multiple validation, so don't use @validate decorators.
    @transaction.commit_on_success
    @throttle(10, 60 * 60)  # allow 10 addons an hour
    def create(self, request):
        license_form = LicenseForm(request.POST)

        if not license_form.is_valid():
            return _form_error(license_form)

        new_file_form = XPIForm(request.POST, request.FILES)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        license = license_form.save()

        a = new_file_form.create_addon(user=request.amo_user,
                                       license=license)
        return a

    @check_addon_and_version
    @throttle(10, 60 * 60)  # allow 10 updates an hour
    def update(self, request, addon):
        form = AddonForm(request.PUT, instance=addon)
        if not form.is_valid():
            return _form_error(form)
        a = form.save()
        return a

    @check_addon_and_version
    @throttle(5, 60 * 60)  # Allow 5 delete per hour
    def delete(self, request, addon):
        addon.delete(msg='Deleted via API')
        return rc.DELETED


class BaseApplicationsVersionsHandler(object):

    @classmethod
    def application(cls, av):
        return amo.APP_IDS[av.application_id].short

    @classmethod
    def max(cls, av):
        return av.max.version

    @classmethod
    def min(cls, av):
        return av.min.version


class AnonymousApplicationsVersionsHandler(AnonymousBaseHandler,
                                  BaseApplicationsVersionsHandler):
    allowed_methods = ('GET', )
    model = ApplicationsVersions
    fields = ('application', 'max', 'min',)


class ApplicationsVersionsHandler(BaseHandler,
                                  BaseApplicationsVersionsHandler):
    allowed_methods = ('PUT', 'GET')
    model = ApplicationsVersions
    anonymous = AnonymousApplicationsVersionsHandler
    fields = AnonymousApplicationsVersionsHandler.fields

    @check_addon_and_version
    @throttle(10, 60 * 60)
    def update(self, request, addon, version):
        """
        Note: This API is unfriendly for public usage due to its use of
        formsets.
        """
        form = CompatFormSet(request.PUT or None, queryset=version.apps.all())
        if not form.is_valid():
            resp = rc.BAD_REQUEST
            if not form.is_bound:
                errors = _('No data')
            else:
                errors = ' '.join(form.non_form_errors() +
                        [f.non_field_errors().as_text()[2:]
                        for f in form.forms if f.non_field_errors()])
            resp.write(': %s' % errors)
            return resp

        compats = []
        for compat in form.save(commit=False):
            compat.version = version
            compat.save()
            compats.append(compat)
        return compats


class BaseVersionHandler(object):
    # Custom handler so translated text doesn't look weird
    @classmethod
    def release_notes(cls, version):
        if version.releasenotes:
            return version.releasenotes.localized_string

    @classmethod
    def license(cls, version):
        if version.license:
            return unicode(version.license)

    @classmethod
    def current(cls, version):
        return (version.id == version.addon._current_version_id)


class AnonymousVersionsHandler(AnonymousBaseHandler, BaseVersionHandler):
    model = Version
    allowed_methods = ('GET',)
    fields = ('id', 'addon_id', 'created', 'release_notes', 'version',
              'license', 'current', 'apps',)

    def read(self, request, addon_id, version_id=None):
        if version_id:
            try:
                return Version.objects.get(pk=version_id)
            except:
                return rc.NOT_HERE
        try:
            addon = Addon.objects.get(pk=addon_id)
        except:
            return rc.NOT_HERE

        return addon.versions.all()


class VersionsHandler(BaseHandler, BaseVersionHandler):
    allowed_methods = ('POST', 'PUT', 'DELETE', 'GET',)
    model = Version
    fields = AnonymousVersionsHandler.fields
    exclude = ('approvalnotes', )
    anonymous = AnonymousVersionsHandler

    @check_addon_and_version
    @throttle(5, 60 * 60)  # 5 new versions an hour
    def create(self, request, addon):
        # This has license data
        license_form = LicenseForm(request.POST)

        if not license_form.is_valid():
            return _form_error(license_form)

        new_file_form = XPIForm(request.POST, request.FILES, addon=addon)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        license = license_form.save()
        v = new_file_form.create_version(license=license)
        return v

    @check_addon_and_version
    @throttle(10, 60 * 60)
    def update(self, request, addon, version):
        # This has license data.
        license_form = LicenseForm(request.POST)

        if license_form.is_valid():
            license = license_form.save()
        else:
            license = version.license

        new_file_form = XPIForm(request.PUT, request.FILES, version=version)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        v = new_file_form.update_version(license)
        return v

    @check_addon_and_version
    @throttle(10, 60 * 60)  # allow 10 deletes an hour
    def delete(self, request, addon, version):
        version.delete()
        return rc.DELETED

    @check_addon_and_version
    def read(self, request, addon):
        return addon.versions.all()
