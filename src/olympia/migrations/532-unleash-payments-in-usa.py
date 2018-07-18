import mkt

from mkt.webapps.models import AddonExcludedRegion

from olympia import amo


def run():
    """Unleash payments in USA."""
    (
        AddonExcludedRegion.objects.exclude(addon__premium_type=amo.ADDON_FREE)
        .filter(region=mkt.regions.US.id)
        .delete()
    )
