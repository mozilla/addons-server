import random
import tempfile

from django.conf import settings

from PIL import Image, ImageColor

from olympia.addons.models import Preview
from olympia.devhub.tasks import resize_preview


def generate_addon_preview(addon):
    """
    Generate a screenshot for the given `addon`.
    The fake image will be filled with a random color.

    """
    color = random.choice(list(ImageColor.colormap.keys()))
    im = Image.new('RGB', (320, 480), color)
    p = Preview.objects.create(addon=addon, caption='Screenshot 1', position=1)
    f = tempfile.NamedTemporaryFile(dir=settings.TMP_PATH)
    im.save(f, 'png')
    resize_preview(f.name, p.pk)
