from amo.utils import chunked
from mkt.developers.tasks import generate_image_assets
from mkt.webapps.models import Webapp


def run():
    for chunk in chunked(Webapp.objects.all(), 50):
        for app in chunk:
            try:
                generate_image_assets.delay(app)
            except Exception:
                pass
