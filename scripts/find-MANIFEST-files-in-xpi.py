import logging
import zipfile

from olympia import amo
from olympia.files.models import File


log = logging.getLogger('find-MANIFEST-files-in-xpi')


"""Walk all the XPI files to find those that have META-INF/MANIFEST.mf file.

This file with was not removed by the signing_clients<=0.1.13 on signing, and
thus would result in a "signature not recognizable" error. See bug
https://bugzilla.mozilla.org/show_bug.cgi?id=1169574.
"""
addons = set()
# Only (complete) themes and addons can have XPI files.
for file_ in File.objects.filter(
        version__addon__type__in=[amo.ADDON_EXTENSION, amo.ADDON_THEME],
        is_signed=True):
    try:
        with zipfile.ZipFile(file_.file_path, mode='r') as zf:
            filenames = zf.namelist()
            if u'META-INF/MANIFEST.MF' in filenames:
                addons.add(file_.version.addon.pk)
    except (zipfile.BadZipfile, IOError):
        pass
print ' '.join((str(addon_id) for addon_id in addons))
