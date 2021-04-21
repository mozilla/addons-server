from django.db import models

from olympia import amo
from olympia.amo.models import ModelBase

ENDPOINTS = ('collections', 'search')

ENDPOINT_CHOICES = tuple((ty, ty) for ty in ENDPOINTS)


class Shelf(ModelBase):
    title = models.CharField(max_length=200, help_text='Will be translated.')
    endpoint = models.CharField(
        max_length=200, choices=ENDPOINT_CHOICES, db_column='shelf_type'
    )
    criteria = models.CharField(
        max_length=200,
        help_text='e.g., "?promoted=recommended&sort=random&type=extension" '
        'or the collection slug',
    )
    footer_text = models.CharField(
        max_length=200,
        blank=True,
        help_text='e.g., See more recommended extensions. Will be translated.',
    )
    footer_pathname = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g., collections/4757633/privacy-matters',
    )
    addon_count = models.PositiveSmallIntegerField(
        default=0,
        help_text='0 means the default number (4, or 3 for themes) of add-ons '
        'will be included in shelf responses. Set to override.',
    )
    addon_type = models.PositiveIntegerField(
        choices=amo.ADDON_TYPE.items(),
        db_column='addontype_id',
        default=amo.ADDON_EXTENSION,
    )

    class Meta:
        verbose_name_plural = 'shelves'

    def __str__(self):
        return self.title

    def get_count(self):
        return self.addon_count or (
            3 if self.addon_type == amo.ADDON_STATICTHEME else 4
        )


class ShelfManagement(ModelBase):
    shelf = models.OneToOneField(Shelf, on_delete=models.CASCADE)
    enabled = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    def __str__(self):
        return str(self.shelf)

    class Meta:
        verbose_name_plural = 'homepage shelves'
        constraints = [
            models.UniqueConstraint(fields=('enabled', 'position'), name='position_id')
        ]
