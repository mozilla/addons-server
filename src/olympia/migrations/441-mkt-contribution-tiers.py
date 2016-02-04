from olympia import amo
from market.models import Price
from stats.models import Contribution


def run():
    """
    Attach price tier to existing USD contributions for marketplace.
    """
    contribs = (Contribution.objects
                .filter(price_tier__isnull=True,
                        addon__type=amo.ADDON_WEBAPP))

    for contrib in contribs:
        try:
            contrib.update(
                price_tier=Price.objects.get(price=abs(contrib.amount))
            )
        except (AttributeError, Price.DoesNotExist) as e:
            print str(e)
            continue
