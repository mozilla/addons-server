from amo.utils import chunked
from mkt.constants import APP_IMAGE_SIZES
from mkt.webapps.models import ImageAsset, Webapp


SIZE_SLUGS = [size['slug'] for size in APP_IMAGE_SIZES]


def run():
    """Delete duplicate image assets."""
    for chunk in chunked(Webapp.objects.all(), 50):
        for app in chunk:
            for slug in SIZE_SLUGS:
                assets = ImageAsset.objects.filter(addon=app, slug=slug)
                for asset in assets[1:]:
                    asset.delete()
