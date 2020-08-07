from django.db import models

from olympia.amo.models import ModelBase

ENDPOINTS = ('collections', 'search')

ENDPOINT_CHOICES = tuple((ty, ty) for ty in ENDPOINTS)


class Shelf(ModelBase):
    title = models.CharField(max_length=200)
    endpoint = models.CharField(
        max_length=200, choices=ENDPOINT_CHOICES)
    criteria = models.CharField(
        max_length=200,
        help_text='<i>?recommended=true&sort=random&type=extension</i>')
    footer_text = models.CharField(
        max_length=200, blank=True,
        help_text='<i>See more recommended extensions</i>')
    footer_pathname = models.CharField(
        max_length=255, blank=True,
        help_text='<i>collections/4757633/privacy-matters</i>')

    class Meta:
        verbose_name_plural = 'shelves'

    def __str__(self):
        return self.title
