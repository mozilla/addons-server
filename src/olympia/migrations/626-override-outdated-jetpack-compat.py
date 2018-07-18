from addons.models import Addon, CompatOverride, CompatOverrideRange

from olympia import amo


def run():
    addons = Addon.objects.filter(
        type=amo.ADDON_EXTENSION,
        appsupport__app=amo.FIREFOX.id,
        _current_version__files__jetpack_version__isnull=False,
    ).exclude(_current_version__files__jetpack_version='1.14')

    # Fix invalid compat ranges from last migration
    (
        CompatOverrideRange.objects.filter(
            compat__addon__in=addons,
            type=1,
            app_id=amo.FIREFOX.id,
            min_app_version='0',
            max_app_version='21.*',
            min_version='0',
        ).delete()
    )

    count = 0
    for addon in addons:
        co, created = CompatOverride.objects.get_or_create(
            addon=addon, guid=addon.guid, name=addon.name
        )
        CompatOverrideRange.objects.create(
            compat=co,
            type=1,
            app_id=amo.FIREFOX.id,
            min_app_version='21.*',
            max_app_version='*',
            min_version='0',
            max_version=addon.current_version.version,
        )

        count += 1

    print('Overrode compatibility for %d SDK add-ons.' % count)
