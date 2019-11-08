from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.html import format_html
from django.utils.functional import cached_property

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.amo.urlresolvers import reverse
from olympia.users.models import UserProfile
from django.utils.translation import gettext_lazy as _
from olympia.versions.compare import addon_version_int
from olympia.versions.models import Version


class Block(ModelBase):
    guid = models.CharField(max_length=255, unique=True, null=False)
    min_version = models.CharField(max_length=255, blank=False, default='0')
    max_version = models.CharField(max_length=255, blank=False, default='*')
    url = models.CharField(max_length=255, blank=True)
    reason = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL)
    include_in_legacy = models.BooleanField(
        default=False,
        help_text='Include in legacy xml blocklist too, as well as new v3')

    ACTIVITY_IDS = (
        amo.LOG.BLOCKLIST_BLOCK_ADDED.id,
        amo.LOG.BLOCKLIST_BLOCK_EDITED.id,
        amo.LOG.BLOCKLIST_BLOCK_DELETED.id)

    def __str__(self):
        return f'Block: {self.guid}'

    def __init__(self, *args, **kwargs):
        # Optimized case of creating a Block from Addon so skipping the query.
        addon = kwargs.pop('addon', None)
        if addon:
            kwargs['guid'] = addon.guid
            self.addon = addon
        super().__init__(*args, **kwargs)

    @cached_property
    def addon(self):
        return Addon.unfiltered.filter(
            guid=self.guid).only_translations().first()

    @cached_property
    def addon_versions(self):
        # preload_addon_versions will set this property for us.
        self.preload_addon_versions([self])
        return self.addon_versions

    @classmethod
    def preload_addon_versions(cls, blocks):
        # if you're calling this on a list of blocks it's expected that you've
        # set cached_property self.addon in a db efficient way beforehand.
        addon_ids = [block.addon.id for block in blocks]
        qs = Version.unfiltered.filter(addon_id__in=addon_ids).values(
            'addon_id', 'version', 'channel')
        addons_versions = defaultdict(dict)
        for version in qs:
            addons_versions[str(version['addon_id'])][version['version']] = (
                version['channel'])
        for block in blocks:
            block.addon_versions = addons_versions[str(block.addon.id)]

    def clean(self):
        min_vint = addon_version_int(self.min_version)
        max_vint = addon_version_int(self.max_version)
        if min_vint > max_vint:
            raise ValidationError(
                _('Min version can not be greater than Max version'))

    def is_version_blocked(self, version):
        version_vint = addon_version_int(version)
        min_vint = addon_version_int(self.min_version)
        max_vint = addon_version_int(self.max_version)
        return version_vint >= min_vint and version_vint <= max_vint

    def review_listed_link(self):
        has_listed = any(
            True for v in self.addon_versions.values()
            if v == amo.RELEASE_CHANNEL_LISTED)
        if has_listed:
            url = reverse(
                'reviewers.review',
                kwargs={'addon_id': self.addon.pk})
            return format_html(
                '<a href="{}">{}</a>', url, _('Review Listed'))
        return ''

    def review_unlisted_link(self):
        has_unlisted = any(
            True for v in self.addon_versions.values()
            if v == amo.RELEASE_CHANNEL_UNLISTED)
        if has_unlisted:
            url = reverse(
                'reviewers.review',
                args=('unlisted', self.addon.pk))
            return format_html(
                '<a href="{}">{}</a>', url, _('Review Unlisted'))
        return ''
