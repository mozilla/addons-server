from addons.models import AddonUpsell


def run():
    for upsell in list(AddonUpsell.objects.all()):
        upsell.cleanup()
