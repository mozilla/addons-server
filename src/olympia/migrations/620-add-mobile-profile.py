from olympia import amo
from mkt.webapps.models import AppFeatures, Webapp


def run():
    """Update feature profiles for mobile-only apps requiring qHD."""
    apps = (Webapp.objects
            .filter(addondevicetype__device_type__in=[amo.DEVICE_MOBILE.id,
                                                      amo.DEVICE_GAIA.id])
            .exclude(addondevicetype__device_type__in=[amo.DEVICE_TABLET.id,
                                                       amo.DEVICE_DESKTOP.id]))
    for app in apps:
        for version in app.versions.all():
            af, _ = AppFeatures.objects.get_or_create(version=version)
            af.update(has_qhd=True)
            print('Marked mobile-only app "%s" (version %s) as '
                  'requiring a qHD device' % (app, version))
