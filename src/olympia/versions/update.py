from django.db.models import F
from django.db.transaction import non_atomic_requests
from django.http import JsonResponse
from django.views.decorators.cache import cache_control
from django.urls import reverse

from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.reverse import override_url_prefix
from olympia.constants import applications
from olympia.versions.compare import version_int
from olympia.versions.models import Version


# Valid compatMode parameters
# (see mozilla-central/source/toolkit/mozapps/extensions/internal/XPIInstall.jsm)
COMPAT_MODE_STRICT = 'strict'
COMPAT_MODE_NORMAL = 'normal'
COMPAT_MODE_IGNORE = 'ignore'


class Updater:
    def __init__(self, data):
        self.compat_mode = data.get('compatMode', COMPAT_MODE_STRICT)
        self.app = applications.APP_GUIDS.get(data.get('appID'))
        self.guid = data.get('id')
        self.appversion = data.get('appVersion')

    def check_required_parameters(self):
        return self.app and self.guid and self.appversion

    def get_addon_id(self):
        return (
            Addon.objects.not_disabled_by_mozilla()
            .filter(disabled_by_user=False)
            .filter(guid=self.guid)
            .values_list('id', flat=True)
        ).first()

    def get_update(self, addon_id):
        # Compatibility-wise, clients pass appVersion and compatMode query
        # parameters. The version we return _always_ need to have a min
        # appversion set lower or equal to the appversion passed by the client.
        # On top of this:
        # - if compat mode is "strict", then the version also needs to have a
        #   max appversion higher or equal to the appversion passed by the
        #   client.
        # - if compat mode is "normal", then the version also needs to have a
        #   max appversion higher or equal to the appversion passed by the
        #   client only if its file has strict compatibility set - otherwise
        #   it just needs to have a max version set to a value higher than 0.
        # - if compat mode is "ignore" or any other value, then all versions
        #   are considered without looking at their max appversion.
        strict_compat_mode = self.compat_mode == COMPAT_MODE_STRICT
        client_appversion = version_int(self.appversion)
        appversions = {'min': client_appversion}
        if strict_compat_mode or self.compat_mode == COMPAT_MODE_NORMAL:
            appversions['max'] = client_appversion
        return (
            Version.objects.latest_public_compatible_with(
                self.app.id, appversions, strict_compat_mode=strict_compat_mode
            )
            .select_related('file')
            .annotate(addon_slug=F('addon__slug'))  # Avoids building an Addon instance.
            .no_transforms()
            .filter(addon_id=addon_id)
            .order_by('-pk')
            .first()
        )

    def get_output(self):
        if not self.check_required_parameters():
            return self.get_error_output(), 400
        if addon_id := self.get_addon_id():
            if version := self.get_update(addon_id):
                contents = self.get_success_output(version)
            else:
                contents = self.get_no_updates_output()
        else:
            contents = self.get_error_output()
        return contents, 200

    def get_error_output(self):
        return {}

    def get_no_updates_output(self):
        return {'addons': {self.guid: {'updates': []}}}

    def get_success_output(self, version):
        # The update service bypasses our URL prefixer so we need to override
        # the values to send the right thing to the clients.
        # For the locale we use the special `%APP_LOCALE%` that Firefox will
        # replace with the current locale when using the URL. See
        # mozilla-central/source/toolkit/mozapps/extensions/AddonManager.jsm
        with override_url_prefix(app_name=self.app.short, locale='%APP_LOCALE%'):
            update = {
                'version': version.version,
                'update_link': version.file.get_absolute_url(),
                'applications': {
                    'gecko': {'strict_min_version': version.min_compatible_version}
                },
            }
            if version.file.strict_compatibility:
                update['applications']['gecko'][
                    'strict_max_version'
                ] = version.max_compatible_version
            if version.file.hash:
                update['update_hash'] = version.file.hash
            if version.release_notes_id:
                update['update_info_url'] = absolutify(
                    reverse(
                        'addons.versions.update_info',
                        # Use our addon_slug annotation instead of version.addon.slug
                        # to avoid additional queries.
                        args=(version.addon_slug, version.version),
                    )
                )
        return {'addons': {self.guid: {'updates': [update]}}}


@non_atomic_requests
@cache_control(max_age=60 * 60)
def update(request):
    updater = Updater(request.GET)
    contents, status_code = updater.get_output()
    return JsonResponse(contents, status=status_code)
