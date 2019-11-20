import datetime
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

from .utils import block_activity_log_save


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
        # preload_addon_versions will overwrite this cached_property.
        self.preload_addon_versions([self])
        return self.addon_versions

    @classmethod
    def preload_addon_versions(cls, blocks):
        """Preload block.addon_versions into a list of blocks.
        If you're calling this on a list of blocks it's expected that you've
        # set cached_property self.addon in a db efficient way beforehand.
        """
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


class MultiBlockSubmit(ModelBase):
    input_guids = models.TextField()
    min_version = models.CharField(
        choices=(('0', '0'),), default='0', max_length=1)
    max_version = models.CharField(
        choices=(('*', '*'),), default='*', max_length=1)
    url = models.CharField(max_length=255, blank=True)
    reason = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL)
    include_in_legacy = models.BooleanField(
        default=False,
        help_text='Include in legacy xml blocklist too, as well as new v3')

    @classmethod
    def process_input_guids(cls, guids):
        all_guids = set(guids.splitlines())

        existing = list(Block.objects.filter(guid__in=all_guids))
        remaining = all_guids - {block.guid for block in existing}

        addon_qs = Addon.unfiltered.filter(guid__in=remaining).order_by(
            '-average_daily_users')
        new = [
            Block(addon=addon) for addon in addon_qs.only_translations()]

        invalid = remaining - {block.guid for block in new}

        return {
            'invalid': list(invalid),
            'existing': list(existing),
            'new': list(new),
        }

    def save_to_blocks(self):
        common_args = {
            'min_version': self.min_version,
            'max_version': self.max_version,
            'url': self.url,
            'reason': self.reason,
            'updated_by': self.updated_by,
            'include_in_legacy': self.include_in_legacy,
        }
        processed_guids = self.process_input_guids(self.input_guids)

        objects_to_add = processed_guids['new']
        for obj in objects_to_add:
            for field, val in common_args.items():
                setattr(obj, field, val)
            obj.save()
            block_activity_log_save(obj, change=False)

        objects_to_update = processed_guids['existing']
        common_args.update(modified=datetime.datetime.now())
        for obj in objects_to_update:
            obj.update(**common_args)
            block_activity_log_save(obj, change=True)

        return (objects_to_add, objects_to_update)
