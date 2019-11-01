from django.core.exceptions import ValidationError
from django.db import models

from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.users.models import UserProfile
from django.utils.translation import gettext_lazy as _
from olympia.versions.compare import version_int


class Block(ModelBase):
    addon = models.ForeignKey(
        Addon, null=False, on_delete=models.CASCADE)
    min_version = models.CharField(max_length=255, blank=False, default='0')
    max_version = models.CharField(max_length=255, blank=False, default='*')
    url = models.CharField(max_length=255, blank=True)
    reason = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL)
    include_in_legacy = models.BooleanField(
        default=False,
        help_text='Include in legacy xml blocklist too, as well as new v3')

    def __str__(self):
        return f'Block: {self.guid}'

    @property
    def guid(self):
        return self.addon.guid if self.addon else None

    def clean(self):
        if version_int(self.min_version) > version_int(self.max_version):
            raise ValidationError(
                _('Min version can not be greater than Max version'))
