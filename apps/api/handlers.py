import functools
import json

from django.conf import settings
from django.db import transaction

import commonware.log
import happyforms
from piston.handler import AnonymousBaseHandler, BaseHandler
from piston.utils import rc
from tower import ugettext as _
import waffle

import amo
from access import acl
from addons.forms import AddonForm
from addons.models import Addon, AddonUser
from amo.utils import paginate
from devhub.forms import LicenseForm, NewManifestForm
from devhub import tasks
from files.models import FileUpload, Platform
from users.models import UserProfile
from versions.forms import XPIForm
from versions.models import Version, ApplicationsVersions
from mkt.webapps.models import Webapp

log = commonware.log.getLogger('z.api')


def check_addon_and_version(f):
    """
    Decorator that checks that an addon, and version exist and belong to the
    request user.
    """
    @functools.wraps(f)
    def wrapper(*args, **kw):
        request = args[1]
        addon_id = kw['addon_id']
        try:
            addon = Addon.objects.id_or_slug(addon_id).get()
        except:
            return rc.NOT_HERE
        if not acl.check_addon_ownership(request, addon, viewer=True):
            return rc.FORBIDDEN

        if 'version_id' in kw:
            try:
                version = Version.objects.get(addon=addon, pk=kw['version_id'])
            except Version.DoesNotExist:
                return rc.NOT_HERE
            return f(*args, addon=addon, version=version)
        else:
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
    fields = ('email', 'id', 'username', 'display_name', 'homepage',
              'created', 'modified', 'location', 'occupation')

    def read(self, request):
        email = request.GET.get('email')
        if email:
            if acl.action_allowed(request, 'API.Users', 'View'):
                try:
                    return UserProfile.objects.get(email=email, deleted=False)
                except UserProfile.DoesNotExist:
                    return rc.NOT_FOUND
            else:
                return rc.FORBIDDEN

        return request.amo_user


class AddonsHandler(BaseHandler):
    allowed_methods = ('GET', 'POST', 'PUT', 'DELETE')
    model = Addon

    fields = ('id', 'name', 'eula', 'guid', 'status', 'slug')
    exclude = ('highest_status', 'icon_type')

    # Custom handler so translated text doesn't look weird
    @classmethod
    def name(cls, addon):
        return addon.name.localized_string if addon.name else ''

    # We need multiple validation, so don't use @validate decorators.
    @transaction.commit_on_success
    def create(self, request):
        new_file_form = XPIForm(request, request.POST, request.FILES)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        # License can be optional.
        license = None
        if 'builtin' in request.POST:
            license_form = LicenseForm(request.POST)
            if not license_form.is_valid():
                return _form_error(license_form)
            license = license_form.save()

        addon = new_file_form.create_addon(license=license)
        if not license:
            # If there is no license, we push you to step
            # 5 so that you can pick one.
            addon.submitstep_set.create(step=5)

        return addon

    @check_addon_and_version
    def update(self, request, addon):
        form = AddonForm(request.PUT, instance=addon)
        if not form.is_valid():
            return _form_error(form)
        a = form.save()
        return a

    @check_addon_and_version
    def delete(self, request, addon):
        addon.delete(msg='Deleted via API')
        return rc.DELETED

    def read(self, request, addon_id=None):
        """
        Returns authors who can update an addon (not Viewer role) for addons
        that have not been admin disabled. Optionally provide an addon id.
        """
        if not request.user.is_authenticated():
            return rc.BAD_REQUEST
        ids = (AddonUser.objects.values_list('addon_id', flat=True)
                                .filter(user=request.amo_user,
                                        role__in=[amo.AUTHOR_ROLE_DEV,
                                                  amo.AUTHOR_ROLE_OWNER]))
        qs = (Addon.objects.filter(id__in=ids)
                           .exclude(status=amo.STATUS_DISABLED)
                           .no_transforms())
        if addon_id:
            try:
                return qs.get(id=addon_id)
            except Addon.DoesNotExist:
                rc.NOT_HERE

        paginator = paginate(request, qs)
        return {'objects': paginator.object_list,
                'num_pages': paginator.paginator.num_pages,
                'count': paginator.paginator.count}


class AppsHandler(AddonsHandler):
    allowed_methods = ('GET', 'POST')
    model = Webapp

    fields = ('id', 'name', 'manifest_url', 'status', 'app_slug')
    exclude = ('highest_status', 'icon_type')

    @transaction.commit_on_success
    def create(self, request):
        if not waffle.flag_is_active(request, 'accept-webapps'):
            return rc.BAD_REQUEST

        form = NewManifestForm(request.POST)
        if form.is_valid():
            # This feels like an awful lot of work.
            # But first upload the file and do the validation.
            upload = FileUpload.objects.create()
            tasks.fetch_manifest(form.cleaned_data['manifest'], upload.pk)

            # We must reget the object here since the above has
            # saved changes to the object.
            upload = FileUpload.uncached.get(pk=upload.pk)
            # Check it validated correctly.
            if settings.VALIDATE_ADDONS:
                validation = json.loads(upload.validation)
                if validation['errors']:
                    response = rc.BAD_REQUEST
                    response.write(validation)
                    return response

            # Fetch the addon, the icon and set the user.
            addon = Addon.from_upload(upload,
                        [Platform.objects.get(id=amo.PLATFORM_ALL.id)])
            if addon.has_icon_in_manifest():
                tasks.fetch_icon(addon)
            AddonUser(addon=addon, user=request.amo_user).save()
            addon.update(status=amo.WEBAPPS_UNREVIEWED_STATUS)

        else:
            return _form_error(form)
        return addon


class ApplicationsVersionsHandler(AnonymousBaseHandler):
    model = ApplicationsVersions
    allowed_methods = ('GET', )
    fields = ('application', 'max', 'min')

    @classmethod
    def application(cls, av):
        return unicode(av.application)

    @classmethod
    def max(cls, av):
        return av.max.version

    @classmethod
    def min(cls, av):
        return av.min.version


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
              'license', 'current', 'apps')

    def read(self, request, addon_id, version_id=None):
        if version_id:
            try:
                return Version.objects.get(pk=version_id)
            except:
                return rc.NOT_HERE
        try:
            addon = Addon.objects.id_or_slug(addon_id).get()
        except:
            return rc.NOT_HERE

        return addon.versions.all()


class VersionsHandler(BaseHandler, BaseVersionHandler):
    allowed_methods = ('POST', 'PUT', 'DELETE', 'GET')
    model = Version
    fields = AnonymousVersionsHandler.fields + ('statuses',)
    exclude = ('approvalnotes', )
    anonymous = AnonymousVersionsHandler

    @check_addon_and_version
    def create(self, request, addon):
        new_file_form = XPIForm(request, request.POST, request.FILES,
                                addon=addon)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        license = None
        if 'builtin' in request.POST:
            license_form = LicenseForm(request.POST)
            if not license_form.is_valid():
                return _form_error(license_form)
            license = license_form.save()

        v = new_file_form.create_version(license=license)
        return v

    @check_addon_and_version
    def update(self, request, addon, version):
        new_file_form = XPIForm(request, request.PUT, request.FILES,
                                version=version)

        if not new_file_form.is_valid():
            return _xpi_form_error(new_file_form, request)

        license = None
        if 'builtin' in request.POST:
            license_form = LicenseForm(request.POST)
            if not license_form.is_valid():
                return _form_error(license_form)
            license = license_form.save()

        v = new_file_form.update_version(license)
        return v

    @check_addon_and_version
    def delete(self, request, addon, version):
        version.delete()
        return rc.DELETED

    @check_addon_and_version
    def read(self, request, addon, version=None):
        return version if version else addon.versions.all()


class AMOBaseHandler(BaseHandler):
    """
    A generic Base Handler that automates create, delete, read and update.
    For list, we use a pagination handler rather than just returning all.
    For list, if an id is given, only one object is returned.
    For delete and update the id of the record is required.
    """

    def get_form(self, *args, **kw):
        class Form(happyforms.ModelForm):
            class Meta:
                model = self.model
        return Form(*args, **kw)

    def delete(self, request, id):
        try:
            return self.model.objects.get(pk=id).delete()
        except self.model.DoesNotExist:
            return rc.NOT_HERE

    def create(self, request):
        form = self.get_form(request.POST)
        if form.is_valid():
            return form.save()
        return _form_error(form)

    def read(self, request, id=None):
        if id:
            try:
                return self.model.objects.get(pk=id)
            except self.model.DoesNotExist:
                return rc.NOT_HERE
        else:
            paginator = paginate(request, self.model.objects.all())
            return {'objects': paginator.object_list,
                    'num_pages': paginator.paginator.num_pages,
                    'count': paginator.paginator.count}

    def update(self, request, id):
        try:
            obj = self.model.objects.get(pk=id)
        except self.model.DoesNotExist:
            return rc.NOT_HERE
        form = self.get_form(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return rc.ALL_OK
        return _form_error(form)
