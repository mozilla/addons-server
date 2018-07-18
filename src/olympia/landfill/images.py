import os
import random
import tempfile
import uuid

from django.conf import settings

from PIL import Image, ImageColor

from olympia.addons.models import Preview
from olympia.addons.tasks import save_theme
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.devhub.tasks import resize_preview


def generate_addon_preview(addon):
    """
    Generate a screenshot for the given `addon`.
    The fake image will be filled with a random color.

    """
    color = random.choice(ImageColor.colormap.keys())
    im = Image.new('RGB', (320, 480), color)
    p = Preview.objects.create(addon=addon, caption='Screenshot 1', position=1)
    f = tempfile.NamedTemporaryFile(dir=settings.TMP_PATH)
    im.save(f, 'png')
    resize_preview(f.name, p.pk)


def create_theme_images(theme, placement, hash_):
    """
    Generates 2 images, one in the temp folder and the other in the
    user-media one. Both are needed to generate previews for themes.

    """
    color = random.choice(ImageColor.colormap.keys())
    image = Image.new('RGB', (3000, 200), color)
    tmp_path = os.path.join(
        settings.TMP_PATH, 'persona_{placement}'.format(placement=placement)
    )
    if not os.path.exists(tmp_path):
        os.makedirs(tmp_path)
    tmp_loc = os.path.join(tmp_path, hash_)
    image.save(tmp_loc, 'jpeg')
    media_path = os.path.join(user_media_path('addons'), str(theme.id))
    if not os.path.exists(media_path):
        os.makedirs(media_path)
    media_loc = os.path.join(media_path, hash_)
    image.save(media_loc, 'jpeg')


def generate_theme_images(theme):
    """Generate header images for a given `theme`."""
    header_hash = uuid.uuid4().hex
    create_theme_images(theme, 'header', header_hash)
    persona = theme.persona
    persona.header = header_hash
    persona.save()
    save_theme(header_hash, theme.pk)
