from django.db import models

from olympia.amo.models import ModelBase

CHOICE_TYPES = (
    ('category', 'category'),
    ('collection', 'collection'),
    ('extension', 'extension'),
    ('recommended', 'recommended'),
    ('search', 'search'),
    ('theme', 'theme'),
)


class Shelf(ModelBase):
    title = models.CharField(max_length=200, unique=True)
    shelfType = models.CharField(
        max_length=200, choices=CHOICE_TYPES, verbose_name='type')
    criteria = models.CharField(
        max_length=200,
        help_text="e.g., search/?recommended=true&sort=random&type=extension")
    footerText = models.CharField(
        max_length=200, default="See more", verbose_name="footer text")
    footerPathname = models.CharField(
        max_length=1000, verbose_name="footer pathname",
        help_text="e.g., collections/4757633/privacy-matters")

    class Meta:
        verbose_name_plural = 'shelves'

    def __str__(self):
        return self.title
