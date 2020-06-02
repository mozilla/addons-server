from collections import defaultdict, namedtuple

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.html import format_html
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

import waffle
from django_extensions.db.fields.json import JSONField
from multidb import get_replica

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import chunked
from olympia.users.models import UserProfile
from olympia.versions.compare import addon_version_int
from olympia.versions.models import Version

from .utils import (
    block_activity_log_delete, legacy_delete_blocks,
    legacy_publish_blocks, save_guids_to_blocks, splitlines)


class Block(ModelBase):
    MIN = '0'
    MAX = '*'

    guid = models.CharField(max_length=255, unique=True, null=False)
    min_version = models.CharField(max_length=255, blank=False, default=MIN)
    max_version = models.CharField(max_length=255, blank=False, default=MAX)
    url = models.CharField(max_length=255, blank=True)
    reason = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL)
    include_in_legacy = models.BooleanField(
        default=False,
        help_text='Include in legacy xml blocklist too, as well as new v3')
    legacy_id = models.CharField(
        max_length=255, null=False, default='', db_index=True,
        db_column='kinto_id')
    submission = models.ManyToManyField('BlocklistSubmission')

    ACTIVITY_IDS = (
        amo.LOG.BLOCKLIST_BLOCK_ADDED.id,
        amo.LOG.BLOCKLIST_BLOCK_EDITED.id,
        amo.LOG.BLOCKLIST_BLOCK_DELETED.id,
        amo.LOG.BLOCKLIST_SIGNOFF.id)

    def __str__(self):
        return f'Block: {self.guid}'

    def __init__(self, *args, **kwargs):
        # Optimized case of creating a Block from Addon so skipping the query.
        addon = kwargs.pop('addon', None)
        if addon:
            kwargs['guid'] = addon.guid
            self.addon = addon
        super().__init__(*args, **kwargs)

    def save(self, **kwargs):
        assert self.updated_by
        return super().save(**kwargs)

    @property
    def is_imported_from_legacy_regex(self):
        return self.legacy_id.startswith('*')

    @cached_property
    def addon(self):
        return Addon.unfiltered.filter(
            guid=self.guid).only_translations().first()

    @property
    def average_daily_users(self):
        addon = self.addon
        return addon.average_daily_users if addon else 0

    @cached_property
    def addon_versions(self):
        # preload_addon_versions will overwrite this cached_property.
        self.preload_addon_versions([self])
        return self.addon_versions

    @classmethod
    def preload_addon_versions(cls, blocks):
        """Preload block.addon_versions into a list of blocks."""
        block_guids = [block.guid for block in blocks]
        GUID = 'addon__addonguid__guid'
        qs = (
            Version.unfiltered.filter(**{f'{GUID}__in': block_guids})
                              .order_by('id')
                              .no_transforms()
                              .annotate(**{GUID: models.F(GUID)}))

        all_addon_versions = defaultdict(list)
        for version in qs:
            all_addon_versions[getattr(version, GUID)].append(version)
        for block in blocks:
            block.addon_versions = all_addon_versions[block.guid]

    @cached_property
    def min_version_vint(self):
        return addon_version_int(self.min_version)

    @cached_property
    def max_version_vint(self):
        return addon_version_int(self.max_version)

    def clean(self):
        if self.id:
            # We're only concerned with edits - self.guid isn't set at this
            # point for new instances anyway.
            choices = list(
                version.version for version in self.addon_versions)
            if self.min_version not in choices + [self.MIN]:
                raise ValidationError({'min_version': _('Invalid version')})
            if self.max_version not in choices + [self.MAX]:
                raise ValidationError({'max_version': _('Invalid version')})
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
            True for version in self.addon_versions
            if version.channel == amo.RELEASE_CHANNEL_LISTED)
        if has_listed:
            url = absolutify(reverse(
                'reviewers.review',
                kwargs={'addon_id': self.addon.pk}))
            return format_html(
                '<a href="{}">{}</a>', url, _('Review Listed'))
        return ''

    def review_unlisted_link(self):
        has_unlisted = any(
            True for version in self.addon_versions
            if version.channel == amo.RELEASE_CHANNEL_UNLISTED)
        if has_unlisted:
            url = absolutify(reverse(
                'reviewers.review',
                args=('unlisted', self.addon.pk)))
            return format_html(
                '<a href="{}">{}</a>', url, _('Review Unlisted'))
        return ''

    @cached_property
    def active_submissions(self):
        return BlocklistSubmission.get_submissions_from_guid(self.guid)

    @property
    def is_readonly(self):
        legacy_submit_off = not waffle.switch_is_active(
            'blocklist_legacy_submit')
        return (
            (legacy_submit_off and self.legacy_id) or self.active_submissions)

    @classmethod
    def get_blocks_from_guids(cls, guids):
        """Given a list of guids, return a list of Blocks - either existing
        instances if the guid exists in a Block, or new instances otherwise.
        """
        # load all the Addon instances together
        using_db = get_replica()
        addons = list(Addon.unfiltered.using(using_db).filter(
            guid__in=guids).no_transforms())

        # And then any existing block instances
        existing_blocks = {
            block.guid: block
            for block in cls.objects.using(using_db).filter(guid__in=guids)}

        for addon in addons:
            # get the existing block object or create a new instance
            block = existing_blocks.get(addon.guid, None)
            if block:
                # if it exists hook up the addon instance
                block.addon = addon
            else:
                # otherwise create a new Block
                block = Block(addon=addon)
                existing_blocks[block.guid] = block
        return list(existing_blocks.values())


class BlocklistSubmission(ModelBase):
    SIGNOFF_PENDING = 0
    SIGNOFF_APPROVED = 1
    SIGNOFF_REJECTED = 2
    SIGNOFF_AUTOAPPROVED = 3
    SIGNOFF_PUBLISHED = 4
    SIGNOFF_STATES = {
        SIGNOFF_PENDING: 'Pending',
        SIGNOFF_APPROVED: 'Approved',
        SIGNOFF_REJECTED: 'Rejected',
        SIGNOFF_AUTOAPPROVED: 'No Sign-off',
        SIGNOFF_PUBLISHED: 'Published to Blocks',
    }
    SIGNOFF_STATES_FINISHED = (
        SIGNOFF_REJECTED,
        SIGNOFF_PUBLISHED,
    )
    ACTION_ADDCHANGE = 0
    ACTION_DELETE = 1
    ACTIONS = {
        ACTION_ADDCHANGE: 'Add/Change',
        ACTION_DELETE: 'Delete',
    }
    FakeBlock = namedtuple(
        'FakeBlock', (
            'id', 'guid', 'min_version', 'max_version',
            'is_imported_from_legacy_regex', 'average_daily_users'))

    action = models.SmallIntegerField(
        choices=ACTIONS.items(), default=ACTION_ADDCHANGE)

    input_guids = models.TextField()
    to_block = JSONField(default=[])
    min_version = models.CharField(
        max_length=255, blank=False, default=Block.MIN)
    max_version = models.CharField(
        max_length=255, blank=False, default=Block.MAX)
    url = models.CharField(max_length=255, blank=True)
    reason = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL)
    include_in_legacy = models.BooleanField(
        default=False,
        help_text='Include in legacy xml blocklist too, as well as new v3')
    signoff_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL, related_name='+')
    signoff_state = models.SmallIntegerField(
        choices=SIGNOFF_STATES.items(), default=SIGNOFF_PENDING)

    class Meta:
        db_table = 'blocklist_blocklistsubmission'

    def __str__(self):
        guids = splitlines(self.input_guids)
        repr = [', '.join(guids)]
        if self.url:
            repr.append(str(self.url))
        if self.reason:
            repr.append(str(self.reason))
        # A single uuid-style guid is 38, but otherwise these string limits
        # are pretty arbitrary and just so the str repr isn't _too_ long.
        trimmed = [rep if len(rep) < 40 else rep[0:37] + '...' for rep in repr]
        return f'{self.get_signoff_state_display()}: {"; ".join(trimmed)}'

    def get_changes_from_block(self, block):
        # return a dict with properties that are different from a given block,
        # as a dict of property_name: (old_value, new_value).
        changes = {}
        properties = (
            'min_version', 'max_version', 'url', 'reason', 'include_in_legacy')
        for prop in properties:
            if getattr(self, prop) != getattr(block, prop):
                changes[prop] = (getattr(block, prop), getattr(self, prop))
        return changes

    def clean(self):
        min_vint = addon_version_int(self.min_version)
        max_vint = addon_version_int(self.max_version)
        if min_vint > max_vint:
            raise ValidationError(
                _('Min version can not be greater than Max version'))

    def get_blocks_submitted(self, load_full_objects_threshold=1_000_000_000):
        blocks = self.block_set.all().order_by('id')
        if blocks.count() > load_full_objects_threshold:
            # If we'd be returning too many Block objects, fake them with the
            # minimum needed to display the link to the Block change page.
            blocks = [
                self.FakeBlock(
                    id=block.id,
                    guid=block.guid,
                    min_version=None,
                    max_version=None,
                    is_imported_from_legacy_regex=None,
                    average_daily_users=None,
                )
                for block in blocks]
        return blocks

    def can_user_signoff(self, signoff_user):
        require_different_users = not settings.DEBUG
        different_users = (
            self.updated_by and signoff_user and
            self.updated_by != signoff_user)
        return not require_different_users or different_users

    def all_adu_safe(self):
        threshold = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD

        return all(
            (lambda du: du <= threshold and du)(block['average_daily_users'])
            for block in self.to_block)

    def has_version_changes(self):
        block_ids = [block['id'] for block in self.to_block]

        has_new_blocks = any(not id_ for id_ in block_ids)
        blocks_with_version_changes_qs = Block.objects.filter(
            id__in=block_ids).exclude(
                min_version=self.min_version, max_version=self.max_version)

        return has_new_blocks or blocks_with_version_changes_qs.exists()

    def update_if_signoff_not_needed(self):
        is_pending = self.signoff_state == self.SIGNOFF_PENDING
        add_action = self.action == self.ACTION_ADDCHANGE
        if (
            (is_pending and self.all_adu_safe()) or
            (is_pending and add_action and not self.has_version_changes())
        ):
            self.update(signoff_state=self.SIGNOFF_AUTOAPPROVED)

    @property
    def is_submission_ready(self):
        """Has this submission been signed off, or sign-off isn't required."""
        return (
            self.signoff_state == self.SIGNOFF_AUTOAPPROVED or (
                self.signoff_state == self.SIGNOFF_APPROVED and
                self.can_user_signoff(self.signoff_by)
            )
        )

    def _serialize_blocks(self):

        def serialize_block(block):
            return {
                'id': block.id,
                'guid': block.guid,
                'average_daily_users': block.average_daily_users,
            }

        processed = self.process_input_guids(
            self.input_guids,
            self.min_version,
            self.max_version,
            load_full_objects=False,
            filter_existing=(self.action == self.ACTION_ADDCHANGE))
        return [
            serialize_block(block) for block in processed.get('blocks', [])]

    def save(self, *args, **kwargs):
        if self.input_guids and not self.to_block:
            # serialize blocks so we can save them as JSON
            self.to_block = self._serialize_blocks()
        super().save(*args, **kwargs)

    @classmethod
    def _split_guids_full(cls, guids, v_min, v_max, filter_existing):
        # load all the Addon instances together
        addons_qs = Addon.unfiltered.filter(guid__in=guids).only_translations()
        addons = sorted(
            addons_qs,
            key=lambda addon: addon.average_daily_users,
            reverse=True)
        addon_guid_dict = {addon.guid: addon for addon in addons}

        # And then any existing block instances
        block_qs = Block.objects.filter(guid__in=guids)
        existing_blocks = list(block_qs)
        # hook up block.addon cached_property
        for block in existing_blocks:
            block.addon = addon_guid_dict.get(block.guid)

        if len(guids) == 1 or not filter_existing:
            # We special case a single guid to always update it.
            blocks_to_update_dict = {
                block.guid: block for block in existing_blocks}
        else:
            # identify the blocks that need updating -
            # i.e. not v_min - vmax already
            blocks_to_update_dict = {
                block.guid: block for block in existing_blocks
                if not (
                    block.min_version == v_min and block.max_version == v_max)}
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
                blocks_to_update_dict.get(addon.guid, None) or
                Block(addon=addon))
            blocks.append(block)
        if not filter_existing:
            # we want to be able to delete a block without an addon (which
            # should never happen... but might) so we have to add any missing
            # blocks on too
            blocks.extend(
                block for block in existing_blocks if block not in blocks)
        return blocks, existing_guids

    @classmethod
    def _split_guids_fake(cls, guids, v_min, v_max, filter_existing):
        # load all the Addon instances together
        addons_qs = Addon.unfiltered.filter(guid__in=guids).values_list(
            'guid', 'average_daily_users', named=True)

        addons = sorted(
            addons_qs,
            key=lambda addon: addon.average_daily_users,
            reverse=True)
        adu_lookup = {
            addon.guid: addon.average_daily_users for addon in addons}

        # And then any existing block instances
        block_qs = Block.objects.filter(guid__in=guids).values_list(
            'id', 'guid', 'min_version', 'max_version', 'legacy_id',
            named=True)
        existing_blocks = [
            cls.FakeBlock(
                id=block.id,
                guid=block.guid,
                min_version=block.min_version,
                max_version=block.max_version,
                is_imported_from_legacy_regex=block.legacy_id.startswith('*'),
                average_daily_users=adu_lookup.get(block.guid, -1),
            )
            for block in block_qs]

        if len(guids) == 1 or not filter_existing:
            # We special case a single guid to always update it.
            blocks_to_update_dict = {
                block.guid: block for block in existing_blocks}
        else:
            # identify the blocks that need updating -
            # i.e. not v_min - vmax already
            blocks_to_update_dict = {
                block.guid: block for block in existing_blocks
                if not (
                    block.min_version == v_min and block.max_version == v_max)}
        existing_guids = [
            block.guid for block in existing_blocks
            if block.guid not in blocks_to_update_dict]

        blocks = []
        for addon in addons:
            guid = addon.guid
            if guid in existing_guids:
                # it's an existing block but doesn't need updating
                continue
            # get the existing block object or create a new instance
            block = blocks_to_update_dict.get(guid, None)
            if not block:
                block = cls.FakeBlock(
                    id=None,
                    guid=guid,
                    min_version=Block.MIN,
                    max_version=Block.MAX,
                    is_imported_from_legacy_regex=False,
                    average_daily_users=adu_lookup.get(guid, -1),
                )
            blocks.append(block)
        if not filter_existing:
            # we want to be able to delete a block without an addon (which
            # should never happen... but might) so we have to add any missing
            # blocks on too
            blocks.extend(
                block for block in existing_blocks if block not in blocks)
        return blocks, existing_guids

    @classmethod
    def process_input_guids(cls, guids, v_min, v_max, load_full_objects=True,
                            filter_existing=True):
        """Process a line-return separated list of guids into a list of invalid
        guids, a list of guids that are blocked already for v_min - vmax, and a
        list of Block instances - including new Blocks (unsaved) and existing
        partial Blocks. If `filter_existing` is False, all existing blocks are
        included.

        If `load_full_objects=False` is passed the Block instances are fake
        (namedtuples) with only minimal data available in the "Block" objects:
        Block.guid,
        Block.average_daily_users,
        Block.min_version,
        Block.max_version,
        Block.is_imported_from_legacy_regex
        """
        all_guids = set(splitlines(guids))

        blocks, existing_guids = (
            cls._split_guids_full(all_guids, v_min, v_max, filter_existing)
            if load_full_objects else
            cls._split_guids_fake(all_guids, v_min, v_max, filter_existing))

        invalid_guids = list(
            all_guids - set(existing_guids) - {block.guid for block in blocks})

        return {
            'invalid_guids': invalid_guids,
            'existing_guids': existing_guids,
            'blocks': blocks,
        }

    def save_to_block_objects(self):
        assert self.is_submission_ready
        assert self.action == self.ACTION_ADDCHANGE

        submit_legacy_switch = waffle.switch_is_active(
            'blocklist_legacy_submit')
        fields_to_set = [
            'min_version',
            'max_version',
            'url',
            'reason',
            'updated_by',
        ]
        if submit_legacy_switch:
            fields_to_set.append('include_in_legacy')

        all_guids_to_block = [block['guid'] for block in self.to_block]

        for guids_chunk in chunked(all_guids_to_block, 100):
            blocks = save_guids_to_blocks(
                guids_chunk, self, fields_to_set=fields_to_set)
            if submit_legacy_switch:
                legacy_publish_blocks(blocks)
            self.save()

        self.update(signoff_state=self.SIGNOFF_PUBLISHED)

    def delete_block_objects(self):
        assert self.is_submission_ready
        assert self.action == self.ACTION_DELETE
        block_ids_to_delete = [block['id'] for block in self.to_block]
        submit_legacy_switch = waffle.switch_is_active(
            'blocklist_legacy_submit')
        for ids_chunk in chunked(block_ids_to_delete, 100):
            blocks = list(Block.objects.filter(id__in=ids_chunk))
            Block.preload_addon_versions(blocks)
            for block in blocks:
                block_activity_log_delete(block, submission_obj=self)
            if submit_legacy_switch:
                legacy_delete_blocks(blocks)
            self.save()
            Block.objects.filter(id__in=ids_chunk).delete()

        self.update(signoff_state=self.SIGNOFF_PUBLISHED)

    @classmethod
    def get_submissions_from_guid(cls, guid, excludes=SIGNOFF_STATES_FINISHED):
        return (
            cls.objects.exclude(signoff_state__in=excludes)
                       .filter(to_block__contains=f'"{guid}"'))


class LegacyImport(ModelBase):
    OUTCOME_INCOMPLETE = 0
    OUTCOME_MISSINGGUID = 1
    OUTCOME_NOTFIREFOX = 2
    OUTCOME_BLOCK = 3
    OUTCOME_REGEXBLOCKS = 4
    OUTCOME_NOMATCH = 5
    OUTCOMES = {
        OUTCOME_INCOMPLETE: 'Incomplete',
        OUTCOME_MISSINGGUID: 'Missing GUID',
        OUTCOME_NOTFIREFOX: 'Wrong target application',
        OUTCOME_BLOCK: 'Added block',
        OUTCOME_REGEXBLOCKS: 'Added blocks from regex',
        OUTCOME_NOMATCH: 'No matches',
    }
    legacy_id = models.CharField(
        unique=True, max_length=255, null=False, default='',
        db_column='kinto_id')
    record = JSONField(default={})
    outcome = models.SmallIntegerField(
        default=OUTCOME_INCOMPLETE, choices=OUTCOMES.items())
    timestamp = models.BigIntegerField()

    class Meta:
        db_table = 'blocklist_kintoimport'
