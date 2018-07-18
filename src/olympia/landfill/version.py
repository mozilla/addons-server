import random

from datetime import datetime

from olympia import amo
from olympia.applications.models import AppVersion
from olympia.files.models import File
from olympia.versions.models import ApplicationsVersions, Version


def generate_version(addon, app=None):
    """
    Generate a version for the given `addon` and the optional
    `app`. The `app` is only useful for add-ons (not themes),
    in which case `AppVersion`s and `ApplicationsVersions`
    are created.

    """
    min_app_version = '4.0'
    max_app_version = '50.0'
    version = '%.1f' % random.uniform(0, 2)
    v = Version.objects.create(addon=addon, version=version)
    v.created = v.last_updated = datetime.now()
    v.save()
    if app is not None:  # Not for themes.
        av_min, _ = AppVersion.objects.get_or_create(
            application=app.id, version=min_app_version
        )
        av_max, _ = AppVersion.objects.get_or_create(
            application=app.id, version=max_app_version
        )
        ApplicationsVersions.objects.get_or_create(
            application=app.id, version=v, min=av_min, max=av_max
        )
    File.objects.create(
        filename='%s-%s' % (v.addon_id, v.id),
        version=v,
        platform=amo.PLATFORM_ALL.id,
        status=amo.STATUS_PUBLIC,
    )
    return v
