import os

from django.conf import settings
from django.db import models

from amo.helpers import absolutify
from amo.models import ModelBase


class ProductIcon(ModelBase):
    ext_url = models.CharField(max_length=255, db_index=True)
    # Height/width of square icon as declared in JWT.
    ext_size = models.IntegerField(db_index=True)
    # Height/width of local icon after cache.
    size = models.IntegerField(db_index=True)
    # Image format as told by PIL.
    format = models.CharField(max_length=4)

    def storage_path(self):
        return os.path.join(settings.PRODUCT_ICON_PATH, self._base_path())

    def url(self):
        return absolutify(os.path.join(settings.PRODUCT_ICON_URL,
                                       self._base_path()))

    def _base_path(self):
        ext = self.format.lower()
        if ext == 'jpeg':
            # The CDN only whitelists this extension.
            ext = 'jpg'
        # This creates an intermediate directory to avoid too-many-links
        # errors on Linux, etc
        return '%s/%s.%s' % (self.pk / 1000, self.pk, ext)

    class Meta:
        db_table = 'webpay_product_icons'
