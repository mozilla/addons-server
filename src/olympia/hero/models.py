from django.conf import settings
from django.db import models

from olympia.amo.models import ModelBase
from olympia.discovery.models import DiscoveryItem


GRADIENT_START_COLOR = '#20123A'


class PrimaryHero(ModelBase):
    image = models.CharField(max_length=255)
    background_color = models.CharField(max_length=7)
    enabled = models.BooleanField(db_index=True, null=False, default=False,)
    disco_addon = models.OneToOneField(DiscoveryItem, on_delete=models.CASCADE)

    @property
    def image_path(self):
        return f'{settings.STATIC_URL}img/hero/featured/{self.image}'

    @property
    def gradient(self):
        return {'start': GRADIENT_START_COLOR, 'end': self.background_color}
