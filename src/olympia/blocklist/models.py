import datetime
from collections import defaultdict, namedtuple, OrderedDict

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
    kinto_id = models.CharField(max_length=255, null=False, default='')

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
        qs = Version.unfiltered.filter(addon_id__in=addon_ids).order_by(
            'id').values('addon_id', 'version', 'id', 'channel')
        addons_versions = defaultdict(OrderedDict)
        for version in qs:
            addons_versions[str(version['addon_id'])][version['version']] = (
                version['id'], version['channel'])
        for block in blocks:
            block.addon_versions = addons_versions[str(block.addon.id)]

    @cached_property
    def min_version_vint(self):
        return addon_version_int(self.min_version)

    @cached_property
    def max_version_vint(self):
        return addon_version_int(self.max_version)

    def clean(self):
        if self.min_version_vint > self.max_version_vint:
            raise ValidationError(
                _('Min version can not be greater than Max version'))

    def is_version_blocked(self, version):
        version_vint = addon_version_int(version)
        return (
            version_vint >= self.min_version_vint and
            version_vint <= self.max_version_vint)

    def review_listed_link(self):
        has_listed = any(
            True for id_, chan in self.addon_versions.values()
            if chan == amo.RELEASE_CHANNEL_LISTED)
        if has_listed:
            url = reverse(
                'reviewers.review',
                kwargs={'addon_id': self.addon.pk})
            return format_html(
                '<a href="{}">{}</a>', url, _('Review Listed'))
        return ''

    def review_unlisted_link(self):
        has_unlisted = any(
            True for id_, chan in self.addon_versions.values()
            if chan == amo.RELEASE_CHANNEL_UNLISTED)
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
    def process_input_guids(cls, guids, load_full_objects=True):
        """Process a line-return seperated list of guids into a list of invalid
        guids, a list of guids that are fully blocked already (0 - *), and a
        list of Block instances - including new Blocks (unsaved) and existing
        partial Blocks.

        If `load_full_objects=False` is passed the Block instances are fake
        (namedtuples) with only minimal data available in the "Block" objects:
        Block.guid,
        Block.addon.guid,
        Block.addon.average_daily_users,
        Block.min_version,
        Block.max_version.
        """
        FakeBlock = namedtuple(
            'FakeBlock', ('guid', 'addon', 'min_version', 'max_version'))
        FakeAddon = namedtuple('FakeAddon', ('guid', 'average_daily_users'))
        all_guids = set(guids.splitlines())

        # load all the Addon instances together
        addon_qs = Addon.unfiltered.filter(guid__in=all_guids).order_by(
            '-average_daily_users')
        addons = (
            list(addon_qs.only_translations())
            if load_full_objects else
            [FakeAddon(guid, addon_users)
             for guid, addon_users in addon_qs.values_list(
                'guid', 'average_daily_users')])
        addon_guid_dict = {addon.guid: addon for addon in addons}

        # And then any existing block instances
        block_qs = Block.objects.filter(guid__in=all_guids)
        existing_blocks = (
            list(block_qs)
            if load_full_objects else
            [FakeBlock(guid, addon_guid_dict[guid], min_version, max_version)
             for guid, min_version, max_version in block_qs.values_list(
                'guid', 'min_version', 'max_version')])
        if load_full_objects:
            # hook up block.addon cached_property (FakeBlock sets it above)
            for block in existing_blocks:
                block.addon = addon_guid_dict[block.guid]

        # identify the blocks that need updating (i.e. not 0 - * already)
        blocks_to_update_dict = {
            block.guid: block for block in existing_blocks
            if not (block.min_version == '0' and block.max_version == '*')}
        existing_guids = [
            block.guid for block in existing_blocks
            if block.guid not in blocks_to_update_dict]

        blocks = []
        for addon in addons:
            if addon.guid in existing_guids:
                # it's an existing block but doesn't need updating
                continue
            # get the existing block object or create a new instance
            block = (
                blocks_to_update_dict.get(addon.guid, None) or (
                    Block(addon=addon) if load_full_objects else
                    FakeBlock(addon.guid, addon, '0', '*')
                ))
            blocks.append(block)

        invalid_guids = list(
            all_guids - set(existing_guids) - {block.guid for block in blocks})

        return {
            'invalid_guids': invalid_guids,
            'existing_guids': existing_guids,
            'blocks': blocks,
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

        blocks = processed_guids['blocks']
        Block.preload_addon_versions(blocks)
        modified_datetime = datetime.datetime.now()
        for block in blocks:
            change = bool(block.id)
            for field, val in common_args.items():
                setattr(block, field, val)
            if change:
                setattr(block, 'modified', modified_datetime)
            block.save()
            block_activity_log_save(block, change=change)

        return blocks
