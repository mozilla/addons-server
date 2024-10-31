from datetime import datetime, timedelta

from django.test.utils import override_settings

from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)

from ..models import BlocklistSubmission, BlockType, BlockVersion


class TestBlockVersion(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.addon = addon_factory()
        self.block = block_factory(updated_by=self.user, guid=self.addon.guid)
        self.version = version_factory(addon=self.addon)
        self.version_2 = version_factory(addon=self.addon, version='2.0')

    def test_str(self):
        hard_block_version = BlockVersion.objects.create(
            block=self.block, version=self.version, block_type=BlockType.BLOCKED
        )
        assert str(hard_block_version) == (
            f'Block.id={self.block.id} ' f'(Blocked) -> Version.id={self.version.id}'
        )

        soft_block_version = BlockVersion.objects.create(
            block=self.block, version=self.version_2, block_type=BlockType.SOFT_BLOCKED
        )
        assert str(soft_block_version.reload()) == (
            f'Block.id={self.block.id} '
            f'(Restricted) -> Version.id={self.version_2.id}'
        )


class TestBlocklistSubmissionManager(TestCase):
    def test_delayed(self):
        now = datetime.now()
        BlocklistSubmission.objects.create(delayed_until=None)
        BlocklistSubmission.objects.create(delayed_until=now - timedelta(days=1))
        future = BlocklistSubmission.objects.create(
            input_guids='future@', delayed_until=now + timedelta(days=1)
        )

        assert list(BlocklistSubmission.objects.delayed()) == [future]


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

    def test_is_delayed_submission_ready(self):
        now = datetime.now()
        submission = BlocklistSubmission.objects.create(
            signoff_state=BlocklistSubmission.SIGNOFF_AUTOAPPROVED
        )
        # auto approved submissions with no delay are ready
        assert submission.is_submission_ready

        # not when the submission is delayed though
        submission.update(delayed_until=now + timedelta(days=1))
        assert not submission.is_submission_ready

        # it's ready when the delay date has passed though
        submission.update(delayed_until=now)
        assert submission.is_submission_ready

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
        addon_factory(guid='zero@adu', average_daily_users=0)
        addon_factory(guid='normal@adu', average_daily_users=500)
        addon_factory(guid='high@adu', average_daily_users=999_999)
        submission = BlocklistSubmission.objects.create(
            input_guids='zero@adu\nnormal@adu'
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
        addon = addon_factory(guid='guid@')
        block_factory(addon=addon, updated_by=user_factory(), reason='things')
        new_version = version_factory(addon=addon)
        submission = BlocklistSubmission.objects.create(
            input_guids=addon.guid, changed_version_ids=[]
        )

        submission.to_block = submission._serialize_blocks()
        # reason is chaning, but no versions are being changed
        assert not submission.has_version_changes()

        submission.update(changed_version_ids=[new_version.id])
        assert submission.has_version_changes()

    def test_is_delayed(self):
        now = datetime.now()
        submission = BlocklistSubmission.objects.create(
            signoff_state=BlocklistSubmission.SIGNOFF_AUTOAPPROVED
        )
        assert not submission.is_delayed
        submission.update(delayed_until=now + timedelta(minutes=1))
        assert submission.is_delayed
        submission.update(delayed_until=now - timedelta(minutes=1))
        assert not submission.is_delayed
