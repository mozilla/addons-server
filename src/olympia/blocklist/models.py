from collections import defaultdict, namedtuple

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from multidb import get_replica

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.models import ModelBase
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import chunked
from olympia.users.models import UserProfile
from olympia.versions.compare import VersionString
from olympia.versions.fields import VersionStringField
from olympia.versions.models import Version

from .utils import (
    block_activity_log_delete,
    save_guids_to_blocks,
    splitlines,
)


def no_asterisk(value):
    if '*' in value:
        raise ValidationError(_('%(value)s contains *'), params={'value': value})


class Block(ModelBase):
    MIN = VersionString('0')
    MAX = VersionString('*')

    guid = models.CharField(max_length=255, unique=True, null=False)
    min_version = VersionStringField(
        max_length=255, blank=False, default=MIN, validators=(no_asterisk,)
    )
    max_version = VersionStringField(max_length=255, blank=False, default=MAX)
    url = models.CharField(max_length=255, blank=True)
    reason = models.TextField(blank=True)
    updated_by = models.ForeignKey(UserProfile, null=True, on_delete=models.SET_NULL)
    submission = models.ManyToManyField('BlocklistSubmission')
    average_daily_users_snapshot = models.IntegerField(null=True)

    ACTIVITY_IDS = (
        amo.LOG.BLOCKLIST_BLOCK_ADDED.id,
        amo.LOG.BLOCKLIST_BLOCK_EDITED.id,
        amo.LOG.BLOCKLIST_BLOCK_DELETED.id,
        amo.LOG.BLOCKLIST_SIGNOFF.id,
    )

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

    @classmethod
    def get_addons_for_guids_qs(cls, guids):
        return (
            Addon.unfiltered.filter(guid__in=guids).order_by('-id').only_translations()
        )

    @cached_property
    def addon(self):
        return self.get_addons_for_guids_qs((self.guid,)).first()

    @property
    def current_adu(self):
        return self.addon.average_daily_users if self.addon else 0

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
            .annotate(**{GUID: models.F(GUID)})
        )

        all_addon_versions = defaultdict(list)
        for version in qs:
            all_addon_versions[getattr(version, GUID)].append(version)
        for block in blocks:
            block.addon_versions = all_addon_versions[block.guid]

    def clean(self):
        if self.id:
            # We're only concerned with edits - self.guid isn't set at this
            # point for new instances anyway.
            choices = list(version.version for version in self.addon_versions)
            if self.min_version not in choices + [self.MIN]:
                raise ValidationError({'min_version': _('Invalid version')})
            if self.max_version not in choices + [self.MAX]:
                raise ValidationError({'max_version': _('Invalid version')})
        if self.min_version > self.max_version:
            raise ValidationError(_('Min version can not be greater than Max version'))

    def is_version_blocked(self, version):
        return self.min_version <= version and self.max_version >= version

    def review_listed_link(self):
        has_listed = any(
            True
            for version in self.addon_versions
            if version.channel == amo.RELEASE_CHANNEL_LISTED
        )
        if has_listed:
            url = absolutify(
                reverse('reviewers.review', kwargs={'addon_id': self.addon.pk})
            )
            return format_html('<a href="{}">{}</a>', url, _('Review Listed'))
        return ''

    def review_unlisted_link(self):
        has_unlisted = any(
            True
            for version in self.addon_versions
            if version.channel == amo.RELEASE_CHANNEL_UNLISTED
        )
        if has_unlisted:
            url = absolutify(
                reverse('reviewers.review', args=('unlisted', self.addon.pk))
            )
            return format_html('<a href="{}">{}</a>', url, _('Review Unlisted'))
        return ''

    @cached_property
    def active_submissions(self):
        return BlocklistSubmission.get_submissions_from_guid(self.guid)

    @property
    def is_readonly(self):
        return self.active_submissions

    @classmethod
    def get_blocks_from_guids(cls, guids):
        """Given a list of guids, return a list of Blocks - either existing
        instances if the guid exists in a Block, or new instances otherwise.
        """
        # load all the Addon instances together
        using_db = get_replica()
        addons = list(cls.get_addons_for_guids_qs(guids).using(using_db))

        # And then any existing block instances
        existing_blocks = {
            block.guid: block
            for block in cls.objects.using(using_db).filter(guid__in=guids)
        }

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
        'FakeBlock',
        (
            'id',
            'guid',
            'min_version',
            'max_version',
            'current_adu',
        ),
    )

    action = models.SmallIntegerField(choices=ACTIONS.items(), default=ACTION_ADDCHANGE)

    input_guids = models.TextField()
    to_block = models.JSONField(default=list)
    min_version = VersionStringField(
        max_length=255, blank=False, default=Block.MIN, validators=(no_asterisk,)
    )
    max_version = VersionStringField(max_length=255, blank=False, default=Block.MAX)
    url = models.CharField(
        max_length=255,
        blank=True,
        help_text='The URL related to this block, i.e. the bug filed.',
    )
    reason = models.TextField(
        blank=True,
        help_text='Note this reason will be displayed publicly on the block-addon '
        'pages.',
    )
    updated_by = models.ForeignKey(UserProfile, null=True, on_delete=models.SET_NULL)
    signoff_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL, related_name='+'
    )
    signoff_state = models.SmallIntegerField(
        choices=SIGNOFF_STATES.items(), default=SIGNOFF_PENDING
    )

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
            'min_version',
            'max_version',
            'url',
            'reason',
        )
        for prop in properties:
            if getattr(self, prop) != getattr(block, prop):
                changes[prop] = (getattr(block, prop), getattr(self, prop))
        return changes

    def clean(self):
        if self.min_version > self.max_version:
            raise ValidationError(_('Min version can not be greater than Max version'))

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
                    current_adu=None,
                )
                for block in blocks
            ]
        return blocks

    def can_user_signoff(self, signoff_user):
        require_different_users = not settings.DEBUG
        different_users = (
            self.updated_by and signoff_user and self.updated_by != signoff_user
        )
        return not require_different_users or different_users

    def all_adu_safe(self):
        threshold = settings.DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD

        return all(
            (lambda du: du <= threshold)(block['average_daily_users'])
            for block in self.to_block
        )

    def has_version_changes(self):
        block_ids = [block['id'] for block in self.to_block]

        has_new_blocks = any(not id_ for id_ in block_ids)
        blocks_with_version_changes_qs = Block.objects.filter(id__in=block_ids).exclude(
            min_version=self.min_version, max_version=self.max_version
        )

        return has_new_blocks or blocks_with_version_changes_qs.exists()

    def update_if_signoff_not_needed(self):
        is_pending = self.signoff_state == self.SIGNOFF_PENDING
        add_action = self.action == self.ACTION_ADDCHANGE
        if (is_pending and self.all_adu_safe()) or (
            is_pending and add_action and not self.has_version_changes()
        ):
            self.update(signoff_state=self.SIGNOFF_AUTOAPPROVED)

    @property
    def is_submission_ready(self):
        """Has this submission been signed off, or sign-off isn't required."""
        return self.signoff_state == self.SIGNOFF_AUTOAPPROVED or (
            self.signoff_state == self.SIGNOFF_APPROVED
            and self.can_user_signoff(self.signoff_by)
        )

    def _serialize_blocks(self):
        def serialize_block(block):
            return {
                'id': block.id,
                'guid': block.guid,
                'average_daily_users': block.current_adu,
            }

        processed = self.process_input_guids(
            self.input_guids,
            self.min_version,
            self.max_version,
            load_full_objects=False,
            filter_existing=(self.action == self.ACTION_ADDCHANGE),
        )
        return [serialize_block(block) for block in processed.get('blocks', [])]

    def save(self, *args, **kwargs):
        if self.input_guids and not self.to_block:
            # serialize blocks so we can save them as JSON
            self.to_block = self._serialize_blocks()
        super().save(*args, **kwargs)

    @classmethod
    def _get_fake_blocks_from_guids(cls, guids):
        addons = list(
            Block.get_addons_for_guids_qs(guids).values_list(
                'guid', 'average_daily_users', named=True
            )
        )
        adu_lookup = {addon.guid: addon.average_daily_users for addon in addons}

        # And then any existing block instances
        block_qs = Block.objects.filter(guid__in=guids).values_list(
            'id', 'guid', 'min_version', 'max_version', named=True
        )
        blocks = {
            block.guid: cls.FakeBlock(
                id=block.id,
                guid=block.guid,
                min_version=block.min_version,
                max_version=block.max_version,
                current_adu=adu_lookup.get(block.guid, -1),
            )
            for block in block_qs
        }

        for addon in addons:
            block = blocks.get(addon.guid)
            if block:
                # it's an existing block
                continue
            # create a new instance
            block = cls.FakeBlock(
                id=None,
                guid=addon.guid,
                min_version=Block.MIN,
                max_version=Block.MAX,
                current_adu=adu_lookup.get(addon.guid, -1),
            )
            blocks[addon.guid] = block
        return list(blocks.values())

    @classmethod
    def process_input_guids(
        cls, input_guids, v_min, v_max, *, load_full_objects=True, filter_existing=True
    ):
        """Process a line-return separated list of guids into a list of invalid
        guids, a list of guids that are blocked already for v_min - vmax, and a
        list of Block instances - including new Blocks (unsaved) and existing
        partial Blocks. If `filter_existing` is False, all existing blocks are
        included.

        If `load_full_objects=False` is passed the Block instances are fake
        (namedtuples) with only minimal data available in the "Block" objects:
        Block.guid,
        Block.current_adu,
        Block.min_version,
        Block.max_version,
        """
        all_guids = set(splitlines(input_guids))

        unfiltered_blocks = (
            Block.get_blocks_from_guids(all_guids)
            if load_full_objects
            else cls._get_fake_blocks_from_guids(all_guids)
        )

        if len(all_guids) == 1 or not filter_existing:
            # We special case a single guid to always update it.
            blocks = unfiltered_blocks
            existing_guids = []
        else:
            # unfiltered_blocks contains blocks that don't need to be updated.
            blocks = [
                block
                for block in unfiltered_blocks
                if not block.id
                or block.min_version != v_min
                or block.max_version != v_max
            ]
            existing_guids = [
                block.guid for block in unfiltered_blocks if block not in blocks
            ]

        blocks.sort(key=lambda block: block.current_adu, reverse=True)
        invalid_guids = list(
            all_guids - set(existing_guids) - {block.guid for block in blocks}
        )

        return {
            'invalid_guids': invalid_guids,
            'existing_guids': existing_guids,
            'blocks': blocks,
        }

    def save_to_block_objects(self):
        assert self.is_submission_ready
        assert self.action == self.ACTION_ADDCHANGE

        fields_to_set = [
            'min_version',
            'max_version',
            'url',
            'reason',
            'updated_by',
        ]
        all_guids_to_block = [block['guid'] for block in self.to_block]

        for guids_chunk in chunked(all_guids_to_block, 100):
            save_guids_to_blocks(guids_chunk, self, fields_to_set=fields_to_set)
            self.save()

        self.update(signoff_state=self.SIGNOFF_PUBLISHED)

    def delete_block_objects(self):
        assert self.is_submission_ready
        assert self.action == self.ACTION_DELETE
        block_ids_to_delete = [block['id'] for block in self.to_block]
        for ids_chunk in chunked(block_ids_to_delete, 100):
            blocks = list(Block.objects.filter(id__in=ids_chunk))
            Block.preload_addon_versions(blocks)
            for block in blocks:
                block_activity_log_delete(block, submission_obj=self)
            self.save()
            Block.objects.filter(id__in=ids_chunk).delete()

        self.update(signoff_state=self.SIGNOFF_PUBLISHED)

    @classmethod
    def get_submissions_from_guid(cls, guid, excludes=SIGNOFF_STATES_FINISHED):
        return cls.objects.exclude(signoff_state__in=excludes).filter(
            to_block__contains={'guid': guid}
        )
