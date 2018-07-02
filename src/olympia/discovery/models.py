from django.db import models

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase


class DiscoveryItem(ModelBase):
    addon = models.OneToOneField(
        Addon, on_delete=models.CASCADE,
        help_text='Add-on id this item will point to (If you do not know the '
                  'id, paste the slug instead and it will be transformed '
                  'automatically for you. If you have access to the add-on '
                  'admin page, you can use the magnifying glass to see '
                  'all available add-ons.')
    custom_addon_name = models.CharField(
        max_length=255, blank=True,
        help_text='Custom add-on name, if needed for space constraints. '
                  'Will be used in the heading if present, but will *not* be '
                  'translated.')
    custom_heading = models.CharField(
        max_length=255, blank=True,
        help_text='Short text used in the header. Can contain the following '
                  'special tags: {start_sub_heading}, {addon_name}, '
                  '{end_sub_heading}. Will be translated.')
    custom_description = models.TextField(
        blank=True, help_text='Longer text used to describe an add-on. Should '
                              'not contain any HTML or special tags. Will be '
                              'translated.')

    def __unicode__(self):
        return unicode(self.addon)
