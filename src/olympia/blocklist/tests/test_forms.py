from django.contrib import admin as admin_site
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from waffle.testutils import override_switch

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.blocklist.admin import BlocklistSubmissionAdmin
from olympia.blocklist.forms import MultiAddForm, MultiDeleteForm
from olympia.blocklist.models import Block, BlocklistSubmission


class LegacySyncCheckMixin():
    def test_v2_blocks_cant_be_edited(self):
        data = {
            'guids': 'any@thing\nsecond@thing',
        }
        anyblock = Block.objects.create(
            guid='any@thing', updated_by=user_factory())
        Block.objects.create(guid='second@thing', updated_by=user_factory())

        form = MultiDeleteForm(data=data)
        form.is_valid()
        form.clean()  # would raise

        # Give any@thing a .kinto_id so its sync'd with legacy blocklist
        anyblock.update(kinto_id='123456')
        form.is_valid()
        with self.assertRaises(ValidationError):
            form.clean()

        # except if the legacy submit waffle is enabled
        with override_switch('blocklist_legacy_submit', active=True):
            form.clean  # would raise


class TestBlocklistSubmissionForm(LegacySyncCheckMixin, TestCase):
    def setUp(self):
        self.new_addon = addon_factory(
            guid='any@new', average_daily_users=100,
            version_kw={'version': '5.56'})
        self.another_new_addon = addon_factory(
            guid='another@new', average_daily_users=100000,
            version_kw={'version': '34.545'})
        self.existing_one_to_ten = Block.objects.create(
            addon=addon_factory(guid='partial@existing'),
            min_version='1',
            max_version='10',
            updated_by=user_factory())
        self.existing_zero_to_max = Block.objects.create(
            addon=addon_factory(
                guid='full@existing', average_daily_users=99,
                version_kw={'version': '10'}),
            min_version='0',
            max_version='*',
            updated_by=user_factory())

    def test_existing_blocks_no_existing(self):
        data = {
            'input_guids': 'any@new\nanother@new',
            'min_version': '0',
            'max_version': '*',
            'existing_min_version': '1',
            'existing_max_version': '10'}
        block_admin = BlocklistSubmissionAdmin(
            model=BlocklistSubmission, admin_site=admin_site)
        request = RequestFactory().get('/')

        # All new guids should always be fine
        form = block_admin.get_form(request=request)(data=data)
        form.is_valid()
        form.clean()  # would raise if there needed to be a recalculation

    def test_existing_blocks_some_existing(self):
        data = {
            'input_guids': 'full@existing',
            'min_version': '0',
            'max_version': '*',
            'existing_min_version': '1',
            'existing_max_version': '10'}
        block_admin = BlocklistSubmissionAdmin(
            model=BlocklistSubmission, admin_site=admin_site)
        request = RequestFactory().get('/')

        # A single guid is always updated so checks are bypassed
        form = block_admin.get_form(request=request)(data=data)
        form.is_valid()
        form.clean()  # would raise

        # Two or more guids trigger the checks
        data.update(input_guids='partial@existing\nfull@existing')
        form = block_admin.get_form(request=request)(data=data)
        form.is_valid()
        with self.assertRaises(ValidationError):
            form.clean()

        # Not if the existing min/max versions match, i.e. they've not been
        # changed
        data.update(
            existing_min_version=data['min_version'],
            existing_max_version=data['max_version'])
        form = block_admin.get_form(request=request)(data=data)
        form.is_valid()
        form.clean()  # would raise

        # It should also be okay if the min/max *have* changed but the blocks
        # affected are the same
        data = {
            'input_guids': 'partial@existing\nfull@existing',
            'min_version': '56',
            'max_version': '156',
            'existing_min_version': '23',
            'existing_max_version': '123'}
        form = block_admin.get_form(request=request)(data=data)
        form.is_valid()
        form.clean()  # would raise

    def test_all_existing_blocks_but_delete_action(self):
        data = {
            'input_guids': 'any@thing\nsecond@thing',
            'action': BlocklistSubmission.ACTION_DELETE}
        block_admin = BlocklistSubmissionAdmin(
            model=BlocklistSubmission, admin_site=admin_site)
        request = RequestFactory().get('/')

        # checks are bypassed if action != BlocklistSubmission.ACTION_ADDCHANGE
        form = block_admin.get_form(request=request)(data=data)
        form.is_valid()
        form.clean()  # would raise

        # Even if min_version or max_version are provided
        data.update(
            min_version='0',
            max_version='*',
            existing_min_version='1234',
            existing_max_version='4567')
        form = block_admin.get_form(request=request)(data=data)
        form.is_valid()
        form.clean()  # would raise


class TestMultiDeleteForm(LegacySyncCheckMixin, TestCase):
    def test_guids_must_exist_for_block_deletion(self):
        data = {
            'guids': 'any@thing\nsecond@thing',
        }
        Block.objects.create(guid='any@thing', updated_by=user_factory())

        form = MultiDeleteForm(data=data)
        form.is_valid()
        with self.assertRaises(ValidationError):
            # second@thing doesn't exist as a block
            form.clean()

        Block.objects.create(guid='second@thing', updated_by=user_factory())
        form.is_valid()
        form.clean()  # would raise

        # except if one of the Blocks is already being changed/deleted
        bls = BlocklistSubmission.objects.create(
            input_guids=data['guids'],
            action=BlocklistSubmission.ACTION_DELETE)
        bls.save()
        form.is_valid()
        with self.assertRaises(ValidationError):
            form.clean()


class TestMultiAddForm(LegacySyncCheckMixin, TestCase):
    def test_guid_must_exist_in_database(self):
        data = {
            'guids': 'any@thing',
        }

        form = MultiAddForm(data=data)
        form.is_valid()
        with self.assertRaises(ValidationError):
            # any@thing doesn't exist
            form.clean()

        # but that check is bypassed for multiple guids
        # (which are highlighted on the following page instead)
        data = {
            'guids': 'any@thing\nsecond@thing',
        }

        form = MultiAddForm(data=data)
        addon_factory(guid='any@thing')
        Block.objects.create(guid='any@thing', updated_by=user_factory())
        addon_factory(guid='second@thing')
        form.is_valid()
        form.clean()  # would raise

        # except if one of the Blocks is already being changed/deleted
        bls = BlocklistSubmission.objects.create(
            input_guids=data['guids'],
            action=BlocklistSubmission.ACTION_ADDCHANGE)
        bls.save()
        form.is_valid()
        with self.assertRaises(ValidationError):
            form.clean()
