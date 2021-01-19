from django.db import models

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ModelBase, OnChangeMixin


class DiscoveryItem(OnChangeMixin, ModelBase):
    addon = models.OneToOneField(
        Addon,
        on_delete=models.CASCADE,
        help_text='Add-on id this item will point to (If you do not know the '
        'id, paste the slug instead and it will be transformed '
        'automatically for you. If you have access to the add-on '
        'admin page, you can use the magnifying glass to see '
        'all available add-ons.',
    )
    custom_description = models.TextField(
        blank=True,
        help_text='Longer text used to describe an add-on. Should '
        'not contain any HTML or special tags. Will be '
        'translated.',
    )
    position = models.PositiveSmallIntegerField(
        default=0,
        blank=True,
        db_index=True,
        help_text='Position in the discovery pane when telemetry-aware '
        'recommendations are off (editorial fallback). '
        'The lower the number, the higher the item will appear in '
        'the page. If left blank or if the value is 0, the item '
        'will not appear unless part of telemetry-aware '
        'recommendations.',
    )
    position_china = models.PositiveSmallIntegerField(
        default=0,
        blank=True,
        db_index=True,
        help_text='Position in the discovery pane in China '
        '(See position field above).',
    )
    position_override = models.PositiveSmallIntegerField(
        default=0,
        blank=True,
        db_index=True,
        help_text='Position in the discovery pane when telemetry-aware '
        'recommendations are on but we want to override them.'
        '(See position field above).',
    )

    def __str__(self):
        return str(self.addon)

    @property
    def should_fallback_to_addon_summary(self):
        return bool(self.addon.type == amo.ADDON_EXTENSION and self.addon.summary)
