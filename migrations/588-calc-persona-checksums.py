from celeryutils import task
import commonware.log
from PIL import Image

from addons.forms import make_checksum
from addons.models import Persona
from amo.decorators import write
from amo.utils import chunked

log = commonware.log.getLogger('z.addons')


@task
@write
def calc_checksum(theme_id, **kw):
    theme = Persona.objects.get(id=theme_id)
    header = theme.header_path
    footer = theme.footer_path

    # Delete invalid themes that are not images (e.g. PDF, EXE).
    try:
        Image.open(header)
        Image.open(footer)
    except IOError:
        theme.addon.delete()
        theme.delete()
        return

    # Calculate checksum and save.
    try:
        theme.checksum = make_checksum(header, footer)
        theme.save()
    except Exception as e:
        log.error(str(e))


def run():
    """Calculate checksums for all themes."""
    pks = Persona.objects.filter(checksum='').values_list('id', flat=True)
    for chunk in chunked(pks, 1000):
        [calc_checksum.delay(pk) for pk in chunk]
