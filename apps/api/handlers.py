from django.db import transaction

import commonware.log
from piston.handler import BaseHandler
from piston.utils import rc, throttle
from tower import ugettext as _

from access import acl
from addons.forms import AddonForm
from addons.models import Addon
from users.models import UserProfile
from versions.forms import LicenseForm, XPIForm

log = commonware.log.getLogger('z.api')


class UserHandler(BaseHandler):
    allowed_methods = ('GET',)
    model = UserProfile
    fields = ('email',)

    def read(self, request):
        try:
            user = UserProfile.objects.get(user=request.user)
            return user
        except UserProfile.DoesNotExist:
            return None


class AddonsHandler(BaseHandler):
    allowed_methods = ('POST', 'PUT')
    model = Addon
    fields = ('id', 'name', 'eula')
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
            resp = rc.BAD_REQUEST
            error = ', '.join(license_form.errors['__all__'])
            resp.write(': ' +
                       # L10n: {0} is comma separated errors for license.
                       _(u'Invalid license data provided: {0}').format(error))
            log.debug(error)
            return resp

        new_file_form = XPIForm(request.POST, request.FILES)

        if not new_file_form.is_valid():
            resp = rc.BAD_REQUEST
            resp.write(': ' + _('Addon did not validate.'))
            log.debug('Addon did not validate for %s' % request.amo_user)
            return resp

        license_id = license_form.get_id_or_create()

        a = new_file_form.create_addon(user=request.amo_user,
                                       license_id=license_id)
        return a

    @throttle(10, 60 * 60)  # allow 10 updates an hour
    def update(self, request, addon_id):
        a = Addon.objects.get(pk=addon_id)
        if not acl.check_ownership(request, a):
            return rc.FORBIDDEN

        form = AddonForm(request.PUT, instance=a)
        if not form.is_valid():
            return rc.BAD_REQUEST
        a = form.save()
        return a
