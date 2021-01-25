from django.db import models

from olympia.amo.models import ModelBase

ENDPOINTS = ('collections', 'search', 'search-themes')

ENDPOINT_CHOICES = tuple((ty, ty) for ty in ENDPOINTS)


class Shelf(ModelBase):
    title = models.CharField(max_length=200)
    endpoint = models.CharField(
        max_length=200, choices=ENDPOINT_CHOICES, db_column='shelf_type'
    )
    criteria = models.CharField(
        max_length=200,
        help_text='e.g., "?promoted=recommended&sort=random&type=extension" '
        'or the collection slug',
    )
    footer_text = models.CharField(
        max_length=200, blank=True, help_text='e.g., See more recommended extensions'
    )
    footer_pathname = models.CharField(
        max_length=255,
        blank=True,
        help_text='e.g., collections/4757633/privacy-matters',
    )

    class Meta:
        verbose_name_plural = 'shelves'

    def __str__(self):
        return self.title

    def get_count(self):
        if self.endpoint in ('search-themes',):
            return 3
        else:
            return 4


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
