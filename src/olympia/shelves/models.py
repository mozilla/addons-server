from collections import namedtuple
from urllib import parse

from django.db import models
from django.utils.functional import cached_property

from olympia import amo
from olympia.amo.models import ModelBase
from olympia.tags.models import Tag


class Shelf(ModelBase):
    Endpoints = namedtuple('Endpoints', ['COLLECTIONS', 'SEARCH', 'RANDOM_TAG'])(
        'collections', 'search', 'random-tag'
    )
    ENDPOINT_CHOICES = tuple((endpoint, endpoint) for endpoint in Endpoints)

    title = models.CharField(
        max_length=70,
        help_text='Will be translated. `random-tag` shelves can use {tag} in the text, '
        'which will be substituted for the random tag selected.',
    )
    endpoint = models.CharField(
        max_length=20, choices=ENDPOINT_CHOICES, db_column='shelf_type'
    )
    criteria = models.CharField(
        max_length=200,
        help_text='e.g., "?promoted=recommended&sort=random&type=extension" '
        'or the collection slug',
    )
    footer_text = models.CharField(
        max_length=70,
        blank=True,
        help_text='e.g., See more recommended extensions. Will be translated. '
        '`random-tag` shelves can use {tag} in the text, which will be substituted for '
        'the random tag selected.',
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
    enabled = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = 'shelves'

    def __str__(self):
        return self.title

    def get_count(self):
        return self.addon_count or (
            3 if self.addon_type == amo.ADDON_STATICTHEME else 4
        )

    @cached_property
    def tag(self):
        return (
            Tag.objects.order_by('?').first().tag_text
            if self.endpoint == self.Endpoints.RANDOM_TAG
            else None
        )

    def get_param_dict(self):
        params = dict(parse.parse_qsl(self.criteria.strip('?')))
        if self.endpoint == self.Endpoints.RANDOM_TAG:
            params['tag'] = self.tag
        return params
