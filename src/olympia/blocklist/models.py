from collections import defaultdict, namedtuple
from datetime import datetime
from types import DynamicClassAttribute

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from multidb import get_replica

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.enum import EnumChoices
from olympia.amo.fields import PositiveTinyIntegerField
from olympia.amo.models import BaseQuerySet, ManagerBase, ModelBase
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.utils import chunked
from olympia.users.models import UserProfile
from olympia.versions.models import Version

from .utils import (
    delete_versions_from_blocks,
    save_versions_to_blocks,
    splitlines,
)


class Block(ModelBase):
    guid = models.CharField(max_length=255, unique=True, null=False)
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
    def get_addons_for_guids_qs(cls, guids, with_names_and_authors=True):
        qs = Addon.unfiltered.filter(guid__in=guids).order_by('-id').only_translations()
        if with_names_and_authors:
            qs = qs.only_translations().transform(Addon.attach_all_authors)
        else:
            qs = qs.no_transforms()
        return qs

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
            .select_related('blockversion')
        )
        all_submission_versions = BlocklistSubmission.get_all_submission_versions()

        all_addon_versions = defaultdict(list)
        for version in qs:
            version.blocklist_submission_id = all_submission_versions.get(version.id, 0)
            all_addon_versions[getattr(version, GUID)].append(version)
        for block in blocks:
            block.addon_versions = all_addon_versions[block.guid]

    def has_soft_blocked_versions(self):
        return self.blockversion_set.filter(block_type=BlockType.SOFT_BLOCKED).exists()

    def has_hard_blocked_versions(self):
        return self.blockversion_set.filter(block_type=BlockType.BLOCKED).exists()

    def review_listed_link(self):
        has_listed = any(
            True
            for version in self.addon_versions
            if version.channel == amo.CHANNEL_LISTED
        )
        if has_listed:
            url = absolutify(
                reverse('reviewers.review', kwargs={'addon_id': self.addon.pk})
            )
            return format_html('· <a href="{}">{}</a>', url, 'Review Listed')
        return ''

    def review_unlisted_link(self):
        has_unlisted = any(
            True
            for version in self.addon_versions
            if version.channel == amo.CHANNEL_UNLISTED
        )
        if has_unlisted:
            url = absolutify(
                reverse('reviewers.review', args=('unlisted', self.addon.pk))
            )
            return format_html('· <a href="{}">{}</a>', url, 'Review Unlisted')
        return ''

    def all_authors_link(self):
        if self.addon and self.addon.all_authors:
            parameter = '?q=' + ','.join(
                map(str, (author.pk for author in self.addon.all_authors))
            )
            url = reverse('admin:users_userprofile_changelist') + parameter
            return format_html('· <a href="{}">{}</a>', url, 'Authors(s)')
        return ''

    @cached_property
    def active_submissions(self):
        return BlocklistSubmission.get_submissions_from_guid(self.guid)

    @classmethod
    def get_blocks_from_guids(cls, guids):
        """Given a list of guids, return a list of Blocks - either existing
        instances if the guid exists in a Block, or new instances otherwise.
        """
        # load all the Addon instances together
        using_db = get_replica()
        addons = list(cls.get_addons_for_guids_qs(guids).using(using_db))

        # And then any existing block instances
        blocks = {
            block.guid: block
            for block in cls.objects.using(using_db).filter(guid__in=guids)
        }

        for addon in addons:
            # get the existing block object or create a new instance
            block = blocks.get(addon.guid, None)
            if block:
                # if it exists hook up the addon instance
                block.addon = addon
            else:
                # otherwise create a new Block
                block = Block(addon=addon)
                blocks[block.guid] = block
        blocks = list(blocks.values())  # flatten to just the Block instances
        Block.preload_addon_versions(blocks)
        return blocks


class BlockType(EnumChoices):
    BLOCKED = 0, '🛑 Hard-Blocked'
    SOFT_BLOCKED = 1, '⚠️ Soft-Blocked'


class BlockVersion(ModelBase):
    version = models.OneToOneField(Version, on_delete=models.CASCADE)
    block = models.ForeignKey(Block, on_delete=models.CASCADE)
    block_type = PositiveTinyIntegerField(
        default=BlockType.BLOCKED,
        choices=BlockType.choices,
    )

    def __str__(self) -> str:
        return (
            f'Block.id={self.block_id} ({self.get_block_type_display()}) '
            f'-> Version.id={self.version_id}'
        )

    def get_user_facing_block_type_display(self):
        """Like get_block_type_display(), but using strings meant for end-users."""
        return _('Blocked') if self.block_type == BlockType.BLOCKED else _('Restricted')


class BlocklistSubmissionQuerySet(BaseQuerySet):
    def delayed(self):
        return self.filter(delayed_until__gt=datetime.now())


class BlocklistSubmissionManager(ManagerBase):
    _queryset_class = BlocklistSubmissionQuerySet

    def delayed(self):
        return self.get_queryset().delayed()


class BlocklistSubmission(ModelBase):
    class SIGNOFF_STATES(EnumChoices):
        PENDING = 0, 'Pending Sign-off'
        APPROVED = 1, 'Approved'
        REJECTED = 2, 'Rejected'
        AUTOAPPROVED = 3, 'Auto Sign-off'
        PUBLISHED = 4, 'Published'

    SIGNOFF_STATES.add_subset('STATES_APPROVED', ('APPROVED', 'AUTOAPPROVED'))
    SIGNOFF_STATES.add_subset('STATES_FINISHED', ('REJECTED', 'PUBLISHED'))

    class _EnumChoicesWithShort(EnumChoices):
        # 'short' extra property is added to describe the short verb we use for
        # each action when displayed next to a version.
        @DynamicClassAttribute
        def short(self):
            return {
                'ADDCHANGE': 'Block',
                'DELETE': 'Unblock',
                'HARDEN': 'Harden',
                'SOFTEN': 'Soften',
            }[self.name]

    class ACTIONS(_EnumChoicesWithShort):
        ADDCHANGE = 0, 'Add/Change Block'
        DELETE = 1, 'Delete Block'
        HARDEN = 2, 'Harden Block'
        SOFTEN = 3, 'Soften Block'

    ACTIONS.add_subset('SAVE_TO_BLOCK_OBJECTS', ('ADDCHANGE', 'HARDEN', 'SOFTEN'))
    ACTIONS.add_subset('DELETE_TO_BLOCK_OBJECTS', ('DELETE',))

    FakeBlockAddonVersion = namedtuple(
        'FakeBlockAddonVersion',
        (
            'id',
            'version',
            'is_blocked',
            'blocklist_submission_id',
        ),
    )
    FakeBlock = namedtuple(
        'FakeBlock',
        (
            'id',
            'guid',
            'current_adu',
            'addon_versions',
        ),
    )

    action = models.SmallIntegerField(
        choices=ACTIONS.choices, default=ACTIONS.ADDCHANGE
    )
    input_guids = models.TextField()
    changed_version_ids = models.JSONField(default=list)
    to_block = models.JSONField(default=list)
    url = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text='The URL related to this block, i.e. the bug filed.',
    )
    reason = models.TextField(
        blank=True,
        null=True,
        help_text='Note this reason will be displayed publicly on the block-addon '
        'pages.',
    )
    updated_by = models.ForeignKey(UserProfile, null=True, on_delete=models.SET_NULL)
    signoff_by = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL, related_name='+'
    )
    signoff_state = models.SmallIntegerField(
        choices=SIGNOFF_STATES.choices, default=SIGNOFF_STATES.PENDING
    )
    delayed_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text='The submission will not be published into blocks before this time.',
    )
    disable_addon = models.BooleanField(default=True)
    block_type = PositiveTinyIntegerField(
        default=BlockType.BLOCKED, choices=BlockType.choices
    )

    objects = BlocklistSubmissionManager()

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
            'versions',
            'url',
            'reason',
        )
        for prop in properties:
            if getattr(self, prop) != getattr(block, prop):
                changes[prop] = (getattr(block, prop), getattr(self, prop))
        return changes

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
        return bool(self.changed_version_ids)

    def update_signoff_for_auto_approval(self):
        is_pending = self.signoff_state == self.SIGNOFF_STATES.PENDING
        add_action = self.action == self.ACTIONS.ADDCHANGE
        if is_pending and (
            self.all_adu_safe() or add_action and not self.has_version_changes()
        ):
            self.update(signoff_state=self.SIGNOFF_STATES.AUTOAPPROVED)

    @property
    def is_submission_ready(self):
        """Has this submission been signed off, or sign-off isn't required."""
        is_auto_approved = self.signoff_state == self.SIGNOFF_STATES.AUTOAPPROVED
        is_signed_off = (
            self.signoff_state == self.SIGNOFF_STATES.APPROVED
            and self.can_user_signoff(self.signoff_by)
        )
        return not self.is_delayed and (is_auto_approved or is_signed_off)

    @property
    def is_delayed(self):
        return bool(self.delayed_until and self.delayed_until > datetime.now())

    def _serialize_blocks(self):
        def serialize_block(block):
            return {
                'id': block.id,
                'guid': block.guid,
                'average_daily_users': block.current_adu,
            }

        processed = self.process_input_guids(
            self.input_guids,
            load_full_objects=False,
            filter_existing=(self.action == self.ACTIONS.ADDCHANGE),
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
            Block.get_addons_for_guids_qs(
                guids, with_names_and_authors=False
            ).values_list('guid', 'average_daily_users', named=True)
        )
        adu_lookup = {addon.guid: addon.average_daily_users for addon in addons}

        # And then any existing block instances
        block_qs = Block.objects.filter(guid__in=guids).values_list(
            'id', 'guid', named=True
        )
        version_qs = (
            Version.unfiltered.filter(addon__addonguid__guid__in=guids)
            .order_by('id')
            .values_list(
                'id',
                'version',
                'blockversion__block_id',
                'addon__addonguid__guid',
                named=True,
            )
        )
        all_submission_versions = cls.get_all_submission_versions()

        all_addon_versions = defaultdict(list)
        for version in version_qs:
            all_addon_versions[version.addon__addonguid__guid].append(
                cls.FakeBlockAddonVersion(
                    version.id,
                    version.version,
                    version.blockversion__block_id is not None,
                    all_submission_versions.get(version.id, 0),
                )
            )

        blocks = {
            block.guid: cls.FakeBlock(
                id=block.id,
                guid=block.guid,
                current_adu=adu_lookup.get(block.guid, -1),
                addon_versions=tuple(all_addon_versions.get(block.guid, [])),
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
                current_adu=adu_lookup.get(addon.guid, -1),
                addon_versions=tuple(all_addon_versions.get(addon.guid, [])),
            )
            blocks[addon.guid] = block
        blocks_list = blocks.values()
        return list(blocks_list)

    @classmethod
    def process_input_guids(
        cls, input_guids, *, load_full_objects=True, filter_existing=True
    ):
        """Process a line-return separated list of guids into a dict:
        {'invalid_guids': a list of invalid guids,
         'existing_guids': a list of guids that are completely blocked already,
         'blocks': a list of Block instances - including new Blocks (unsaved) and
                   existing partial Blocks.
        }
        If `filter_existing=False`, all existing blocks are included in 'blocks' so
        'existing_guids' will be empty.

        If `load_full_objects=False` is passed the Block instances are fake
        (namedtuples) with only minimal data available in the "Block" objects:
        Block.id
        Block.guid,
        Block.current_adu,
        Block.addon_versions,
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
            # Get a list of a blocks from unfiltered_blocks that are either new or
            # not completely blocked.
            blocks = [
                block
                for block in unfiltered_blocks
                if not block.id
                or any(not ver.is_blocked for ver in block.addon_versions)
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
        assert self.action in self.ACTIONS.SAVE_TO_BLOCK_OBJECTS

        all_guids_to_block = [block['guid'] for block in self.to_block]

        for guids_chunk in chunked(all_guids_to_block, 100):
            save_versions_to_blocks(guids_chunk, self)
            self.save()

        self.update(signoff_state=self.SIGNOFF_STATES.PUBLISHED)

    def delete_block_objects(self):
        assert self.is_submission_ready
        assert self.action in self.ACTIONS.DELETE_TO_BLOCK_OBJECTS

        all_guids_to_block = [block['guid'] for block in self.to_block]

        for guids_chunk in chunked(all_guids_to_block, 100):
            # This function will remove BlockVersions and delete the Block if empty
            delete_versions_from_blocks(guids_chunk, self)
            self.save()

        self.update(signoff_state=self.SIGNOFF_STATES.PUBLISHED)

    @classmethod
    def get_submissions_from_guid(cls, guid):
        return cls.objects.exclude(
            signoff_state__in=cls.SIGNOFF_STATES.STATES_FINISHED.values
        ).filter(to_block__contains={'guid': guid})

    @classmethod
    def get_submissions_from_version_id(cls, version_id):
        return cls.objects.exclude(
            signoff_state__in=cls.SIGNOFF_STATES.STATES_FINISHED.values
        ).filter(changed_version_ids__contains=version_id)

    @classmethod
    def get_all_submission_versions(cls):
        submission_qs = cls.objects.exclude(
            signoff_state__in=cls.SIGNOFF_STATES.STATES_FINISHED.values
        ).values_list('id', 'changed_version_ids')
        return {
            ver_id: sub_id for sub_id, id_list in submission_qs for ver_id in id_list
        }
