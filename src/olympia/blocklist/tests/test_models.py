from django.core.exceptions import ValidationError
from django.test.utils import override_settings

from waffle.testutils import override_switch
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.versions.compare import MAX_VERSION_PART

from ..models import Block, BlocklistSubmission


class TestBlock(TestCase):
    def test_is_version_blocked(self):
        block = Block.objects.create(guid='anyguid@', updated_by=user_factory())
        # default is 0 to *
        assert block.is_version_blocked('0')
        assert block.is_version_blocked(str(MAX_VERSION_PART + 1))

        # Now with some restricted version range
        block.update(min_version='2.0')
        assert not block.is_version_blocked('1')
        assert not block.is_version_blocked('2.0b1')
        assert block.is_version_blocked('2')
        assert block.is_version_blocked('3')
        assert block.is_version_blocked(str(MAX_VERSION_PART + 1))
        block.update(max_version='10.*')
        assert not block.is_version_blocked('11')
        assert not block.is_version_blocked(str(MAX_VERSION_PART + 1))
        assert block.is_version_blocked('10')
        assert block.is_version_blocked('9')
        assert block.is_version_blocked('10.1')
        assert block.is_version_blocked('10.%s' % (MAX_VERSION_PART + 1))

    def test_is_imported_from_legacy_regex(self):
        block = Block.objects.create(guid='foo@baa', updated_by=user_factory())
        # no legacy_id
        assert not block.is_imported_from_legacy_regex
        # from a regex legacy_id
        block.update(legacy_id='*123456789')
        assert block.is_imported_from_legacy_regex
        # and a normal one
        block.update(legacy_id='1234567890')
        assert not block.is_imported_from_legacy_regex

    def test_is_readonly(self):
        block = Block.objects.create(guid='foo@baa', updated_by=user_factory())
        # not read only by default
        assert not block.is_readonly
        # but should be if there's an active BlocklistSubmission
        block.active_submissions = [object()]  # just needs to be non-empty
        assert block.is_readonly

        # otherwise legacy_id being non-false means it's imported, so readonly
        del block.active_submissions
        assert not block.is_readonly
        block.legacy_id = 'something'
        assert block.is_readonly
        # except when legacy submissions are enabled to keep it in-sync.
        with override_switch('blocklist_legacy_submit', active=True):
            assert not block.is_readonly

    def test_no_asterisk_in_min_version(self):
        non_user_writeable_fields = (
            'legacy_id',
            'average_daily_users_snapshot',
            'guid',
        )
        block = Block(min_version='123.4', max_version='*', updated_by=user_factory())
        block.full_clean(exclude=non_user_writeable_fields)
        block.min_version = '*'
        with self.assertRaises(ValidationError):
            block.full_clean(exclude=non_user_writeable_fields)
        block.min_version = '0'
        block.full_clean(exclude=non_user_writeable_fields)
        block.min_version = '123.*'
        with self.assertRaises(ValidationError):
            block.full_clean(exclude=non_user_writeable_fields)


class TestBlocklistSubmission(TestCase):
    def test_is_submission_ready(self):
        submitter = user_factory()
        signoffer = user_factory()
        block = BlocklistSubmission.objects.create()

        # No signoff_by so not permitted
        assert not block.signoff_state
        assert not block.signoff_by
        assert not block.is_submission_ready

        # Except when the state is SIGNOFF_AUTOAPPROVED.
        block.update(signoff_state=BlocklistSubmission.SIGNOFF_AUTOAPPROVED)
        assert block.is_submission_ready

        # But if the state is SIGNOFF_APPROVED we need to know the signoff user
        block.update(signoff_state=BlocklistSubmission.SIGNOFF_APPROVED)
        assert not block.is_submission_ready

        # If different users update and signoff, it's permitted.
        block.update(updated_by=submitter, signoff_by=signoffer)
        assert block.is_submission_ready

        # But not if submitter is also the sign off user.
        block.update(signoff_by=submitter)
        assert not block.is_submission_ready

        # Except when that's not enforced locally
        with override_settings(DEBUG=True):
            assert block.is_submission_ready

    def test_get_submissions_from_guid(self):
        addon = addon_factory(guid='guid@')
        block_subm = BlocklistSubmission.objects.create(
            input_guids='guid@\n{sdsd-dssd}'
        )
        # add another one which shouldn't match
        BlocklistSubmission.objects.create(input_guids='gguid@\n{4545-986}')
        assert block_subm.to_block == [
            {
                'id': None,
                'guid': 'guid@',
                'average_daily_users': addon.average_daily_users,
            }
        ]

        # The guid is in a BlocklistSubmission
        assert list(BlocklistSubmission.get_submissions_from_guid('guid@')) == [
            block_subm
        ]

        # But by default we ignored "finished" BlocklistSubmissions
        block_subm.update(signoff_state=BlocklistSubmission.SIGNOFF_PUBLISHED)
        assert list(BlocklistSubmission.get_submissions_from_guid('guid@')) == []

        # Except when we override the states to exclude
        assert list(
            BlocklistSubmission.get_submissions_from_guid('guid@', excludes=())
        ) == [block_subm]

        # And check that a guid that doesn't exist in any submissions is empty
        assert list(BlocklistSubmission.get_submissions_from_guid('ggguid@')) == []

    def test_all_adu_safe(self):
        Block.objects.create(
            addon=addon_factory(guid='zero@adu', average_daily_users=0),
            updated_by=user_factory(),
        )
        Block.objects.create(
            addon=addon_factory(guid='normal@adu', average_daily_users=500),
            updated_by=user_factory(),
        )
        Block.objects.create(
            addon=addon_factory(guid='high@adu', average_daily_users=999_999),
            updated_by=user_factory(),
        )
        submission = BlocklistSubmission.objects.create(
            input_guids='zero@adu\nnormal@adu', min_version=99
        )

        submission.to_block = submission._serialize_blocks()
        # 0 adu is safe when we have unlisted adu
        assert submission.all_adu_safe()

        # safe because just normal adu
        submission.update(input_guids='normal@adu')
        submission.update(to_block=submission._serialize_blocks())
        assert submission.all_adu_safe()

        # unsafe because just a high adu addon included
        submission.update(input_guids='high@adu\nnormal@adu')
        submission.update(to_block=submission._serialize_blocks())
        assert not submission.all_adu_safe()

    def test_has_version_changes(self):
        block = Block.objects.create(
            addon=addon_factory(guid='guid@'), updated_by=user_factory()
        )
        submission = BlocklistSubmission.objects.create(input_guids='guid@')

        submission.to_block = submission._serialize_blocks()
        # no changes to anything
        assert not submission.has_version_changes()

        block.update(min_version='999', reason='things')
        # min_version has changed (and reason)
        assert submission.has_version_changes()

        submission.update(min_version='999')
        # if min_version is the same then it's only the metadata (reason)
        assert not submission.has_version_changes()

    def test_no_asterisk_in_min_version(self):
        non_user_writeable_fields = ('updated_by', 'signoff_by', 'to_block')
        submission = BlocklistSubmission(
            min_version='123.4', max_version='*', input_guids='df@'
        )
        submission.full_clean(exclude=non_user_writeable_fields)
        submission.min_version = '*'
        with self.assertRaises(ValidationError):
            submission.full_clean(exclude=non_user_writeable_fields)
        submission.min_version = '0'
        submission.full_clean(exclude=non_user_writeable_fields)
        submission.min_version = '123.*'
        with self.assertRaises(ValidationError):
            submission.full_clean(exclude=non_user_writeable_fields)
