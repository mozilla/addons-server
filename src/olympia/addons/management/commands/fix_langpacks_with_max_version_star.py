from django.core.management.base import BaseCommand

from olympia import amo
from olympia.core.logger import getLogger
from olympia.versions.compare import version_dict
from olympia.versions.models import AppVersion, Version

log = getLogger('z.fix_langpacks_with_max_version_star')


class Command(BaseCommand):
    help = 'Fix language packs that have a max version compatibility set to *'

    def find_affected_langpacks(self):
        qs = Version.unfiltered.filter(
            addon__type=amo.ADDON_LPAPP, apps__max__version='*').distinct()
        return qs

    def fix_max_appversion_for_version(self, version):
        for app in (amo.FIREFOX, amo.ANDROID):
            if app not in version.compatible_apps:
                log.info(
                    'Version %s for addon %s min version is not compatible '
                    'with %s, skipping this version for that app.',
                    version, version.addon, app.pretty)
                continue
            if version.compatible_apps[app].max.version != '*':
                log.info(
                    'Version %s for addon %s max version is not "*" for %s '
                    'app, skipping this version for that app.',
                    version, version.addon, app.pretty)
                continue
            min_appversion_str = version.compatible_apps[app].min.version
            max_appversion_str = '%d.*' % version_dict(
                min_appversion_str)['major']
            log.warning(
                'Version %s for addon %s min version is %s for %s app, '
                'max will be changed to %s instead of *',
                version, version.addon, min_appversion_str, app.pretty,
                max_appversion_str)
            max_appversion = AppVersion.objects.get(
                application=app.id, version=max_appversion_str)
            version.compatible_apps[app].max = max_appversion
            version.compatible_apps[app].save()

    def handle(self, *args, **options):
        versions = self.find_affected_langpacks()
        log.info(
            'Found %d langpack versions with an incorrect max version',
            versions.count())
        for version in versions:
            log.info('Fixing version %s for addon %s', version, version.addon)
            self.fix_max_appversion_for_version(version)
