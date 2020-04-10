from django.test.utils import override_settings

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.versions.compare import MAX_VERSION_PART

from ..models import Block, BlocklistSubmission


class TestBlock(TestCase):
    def test_is_version_blocked(self):
        block = Block.objects.create(
            guid='anyguid@', updated_by=user_factory())
        # default is 0 to *
        assert block.is_version_blocked('0')
        assert block.is_version_blocked(str(MAX_VERSION_PART + 1))

        # Now with some restricted version range
        block.update(min_version='2.0')
        del block.min_version_vint
        assert not block.is_version_blocked('1')
        assert not block.is_version_blocked('2.0b1')
        assert block.is_version_blocked('2')
        assert block.is_version_blocked('3')
        assert block.is_version_blocked(str(MAX_VERSION_PART + 1))
        block.update(max_version='10.*')
        del block.max_version_vint
        assert not block.is_version_blocked('11')
        assert not block.is_version_blocked(str(MAX_VERSION_PART + 1))
        assert block.is_version_blocked('10')
        assert block.is_version_blocked('9')
        assert block.is_version_blocked('10.1')
        assert block.is_version_blocked('10.%s' % (MAX_VERSION_PART + 1))

    def test_is_imported_from_kinto_regex(self):
        block = Block.objects.create(guid='foo@baa', updated_by=user_factory())
        # no kinto_id
        assert not block.is_imported_from_kinto_regex
        # from a regex kinto_id
        block.update(kinto_id='*123456789')
        assert block.is_imported_from_kinto_regex
        # and a normal one
        block.update(kinto_id='1234567890')
        assert not block.is_imported_from_kinto_regex


class TestMultiBlocklistSubmission(TestCase):
    def test_is_submission_ready(self):
        submitter = user_factory()
        signoffer = user_factory()
        block = BlocklistSubmission.objects.create()

        # No signoff_by so not permitted
        assert not block.signoff_state
        assert not block.signoff_by
        assert not block.is_submission_ready

        # Except when the state is NOTNEEDED.
        block.update(signoff_state=BlocklistSubmission.SIGNOFF_NOTNEEDED)
        assert block.is_submission_ready

        # But if the state is APPROVED we need to know the signoff user
        block.update(signoff_state=BlocklistSubmission.SIGNOFF_APPROVED)
        assert not block.is_submission_ready

        # If different users update and signoff, it's permitted.
        block.update(
            updated_by=submitter,
            signoff_by=signoffer)
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
            input_guids='guid@\n{sdsd-dssd}')
        # add another one which shouldn't match
        BlocklistSubmission.objects.create(input_guids='gguid@\n{4545-986}')
        assert block_subm.to_block == [{
            'id': None,
            'guid': 'guid@',
            'average_daily_users': addon.average_daily_users}]

        # The guid is in a BlocklistSubmission
        assert (
            list(BlocklistSubmission.get_submissions_from_guid('guid@')) ==
            [block_subm])

        # But by default we ignored "finished" BlocklistSubmissions
        block_subm.update(signoff_state=BlocklistSubmission.SIGNOFF_PUBLISHED)
        assert (
            list(BlocklistSubmission.get_submissions_from_guid('guid@')) == [])

        # Except when we override the states to exclude
        assert (
            list(BlocklistSubmission.get_submissions_from_guid(
                'guid@', excludes=())) ==
            [block_subm])

        # And check that a guid that doesn't exist in any submissions is empty
        assert (
            list(BlocklistSubmission.get_submissions_from_guid('ggguid@')) ==
            [])
