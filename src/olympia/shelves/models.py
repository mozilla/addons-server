from django.db import models

from olympia.amo.models import ModelBase

SHELF_TYPES = (
    'category', 'collection', 'extension', 'recommended', 'search', 'theme')

SHELF_TYPE_CHOICES = tuple((ty, ty) for ty in SHELF_TYPES)


class Shelf(ModelBase):
    title = models.CharField(max_length=200)
    shelf_type = models.CharField(
        max_length=200, choices=SHELF_TYPE_CHOICES, verbose_name='type')
    criteria = models.CharField(
        max_length=200,
        help_text="e.g., ?recommended=true&sort=random&type=extension")
    footer_text = models.CharField(
        max_length=200, blank=True,
        help_text="e.g., See more recommended extensions")
    footer_pathname = models.CharField(
        max_length=255, blank=True,
        help_text="e.g., collections/4757633/privacy-matters")

    class Meta:
        verbose_name_plural = 'shelves'

    def __str__(self):
        return self.title
