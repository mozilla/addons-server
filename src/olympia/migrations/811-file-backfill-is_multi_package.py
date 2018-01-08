import olympia.core.logger

from olympia import amo
from olympia.files.models import File
from olympia.files.utils import parse_addon


log = olympia.core.logger.getLogger('backfill-files-is_multi_package')


def run():
    """Walk the themes and addons files to check if they're multi-package XPIs.

    https://developer.mozilla.org/en-US/docs/Multiple_Item_Packaging

    If they are, set File.is_multi_package = True
    """
    # Disable this as a migration, it's taking too long, move it to a
    # standalone script.
    return
    # Only (complete) themes and addons can have multi-package XPIs.
    for file_ in File.objects.filter(
            version__addon__type__in=[amo.ADDON_EXTENSION, amo.ADDON_THEME]):
        try:
            data = parse_addon(file_.file_path, addon=file_.version.addon)
            if data.get('is_multi_package'):
                file_.update(is_multi_package=True)
        except Exception:
            log.error('Failed checking file {0}'.format(file_.pk))
