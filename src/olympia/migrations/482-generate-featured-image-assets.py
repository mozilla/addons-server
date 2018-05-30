from amo.utils import chunked
from mkt.developers.tasks import generate_image_assets
from mkt.webapps.models import Webapp


def run():
    """Generate featured tiles."""
    for chunk in chunked(Webapp.objects.all(), 50):
        for app in chunk:
            generate_image_assets.delay(app, slug='featured_tile')
            print(u'Generated feature tile for app %d' % app.id)
