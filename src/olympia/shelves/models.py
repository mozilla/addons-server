import requests

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import ugettext_lazy as _

from olympia.amo.models import ModelBase

SHELF_TYPES = (
    'category', 'collection', 'extension', 'recommended', 'search', 'theme')

SHELF_TYPE_CHOICES = tuple((ty, ty) for ty in SHELF_TYPES)


def validate_criteria(value):
    url = "https://addons.mozilla.org/api/v4/addons/{}"
    response = requests.get(url.format(value))
    results = response.json()
    if response.status_code == 404:
        raise ValidationError(_("404 Not Found - Invalid criteria"))
    if response.status_code == 400:
        raise ValidationError(_(results[0]))
    if response.status_code == 200 and len(results['results']) == 0:
        raise ValidationError(_("Check parameters in criteria - e.g., 'type'"))
    return value


class Shelf(ModelBase):
    title = models.CharField(max_length=200)
    shelf_type = models.CharField(
        max_length=200, choices=SHELF_TYPE_CHOICES, verbose_name='type')
    criteria = models.CharField(
        max_length=200, validators=[validate_criteria],
        help_text="e.g., search/?recommended=true&sort=random&type=extension")
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
