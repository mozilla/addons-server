import logging
import os
import site

# Add the parent dir to the python path so we can import manage.
parent_dir = os.path.dirname(__file__)
site.addsitedir(os.path.abspath(os.path.join(parent_dir, '../')))

# manage adds /apps and /lib to the Python path.
import manage  # noqa: we need this so it's a standalone script.

import amo  # noqa
from files.models import File  # noqa
from files.utils import parse_addon  # noqa


log = logging.getLogger('backfill-files-is_multi_package')


"""Walk the themes and addons files to check if they're multi-package XPIs.

https://developer.mozilla.org/en-US/docs/Multiple_Item_Packaging

If they are, set File.is_multi_package = True
"""
# Only (complete) themes and addons can have multi-package XPIs.
for file_ in File.objects.filter(
        version__addon__type__in=[amo.ADDON_EXTENSION, amo.ADDON_THEME]):
    try:
        data = parse_addon(file_.file_path, addon=file_.version.addon)
        if data.get('is_multi_package'):
            log.info('Found multi-package: {0}'.format(file_.file_path))
            file_.update(is_multi_package=True)
    except:
        log.error('Failed checking file {0}'.format(file_.pk))
