from django.db.models import F
from django.db.transaction import non_atomic_requests
from django.http import JsonResponse
from django.views.decorators.cache import cache_control
from django.urls import reverse

import olympia.core.logger
from olympia.addons.models import Addon
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.reverse import override_url_prefix
from olympia.constants import applications
from olympia.versions.compare import version_int
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.update')


class Updater:
    def __init__(self, data):
        self.compat_mode = data.get('compatMode', 'strict')
        self.app = applications.APP_GUIDS.get(data.get('appID'))
        self.guid = data.get('id')
        self.appversion = data.get('appVersion')

    def check_required_parameters(self):
        if not self.app or not self.guid or not self.appversion:
            return False
        return True

    def get_addon_id(self):
        try:
            addon_id = (
                Addon.objects.not_disabled_by_mozilla()
                .filter(disabled_by_user=False)
                .filter(guid=self.guid)
                .values_list('id', flat=True)
            )[0]

        except IndexError:
            return False
        return addon_id

    def get_update(self, addon_id):
        strict_compat_mode = self.compat_mode == 'strict'
        appversions = {'min': version_int(self.appversion)}
        if strict_compat_mode or self.compat_mode == 'normal':
            appversions['max'] = appversions['min']
        qs = (
            Version.objects.latest_public_compatible_with(
                self.app.id, appversions, strict_compat_mode=strict_compat_mode
            )
            .select_related('file')
            .annotate(addon_slug=F('addon__slug'))  # Avoids building an Addon instance.
            .no_transforms()
            .filter(addon_id=addon_id)
            .order_by('-pk')
        )
        try:
            version = qs[0]
        except IndexError:
            return False
        return version

    def get_output(self):
        if not self.check_required_parameters():
            return {}, 400
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
