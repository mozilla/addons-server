from django.contrib import admin as admin_site
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from olympia.amo.tests import (
    TestCase,
    addon_factory,
    block_factory,
    user_factory,
    version_factory,
)
from olympia.blocklist.admin import BlocklistSubmissionAdmin
from olympia.blocklist.forms import MultiAddForm, MultiDeleteForm
from olympia.blocklist.models import Block, BlocklistSubmission


class TestBlocklistSubmissionForm(TestCase):
    def setUp(self):
        self.new_addon = addon_factory(
            guid='any@new', average_daily_users=100, version_kw={'version': '5.56'}
        )
        self.another_new_addon = addon_factory(
            guid='another@new',
            average_daily_users=100000,
            version_kw={'version': '34.545'},
        )
        existing_addon = addon_factory(guid='partial@existing')
        version_factory(addon=existing_addon)
        self.existing_block_fully_blocked = block_factory(
            addon=existing_addon,
            updated_by=user_factory(),
        )
        self.existing_block_partially_blocked = block_factory(
            addon=addon_factory(
                guid='full@existing',
                average_daily_users=99,
                version_kw={'version': '10'},
            ),
            updated_by=user_factory(),
        )
        version_factory(addon=self.existing_block_partially_blocked.addon)

    def test_changed_version_ids_choices(self):
        block_admin = BlocklistSubmissionAdmin(
            model=BlocklistSubmission, admin_site=admin_site
        )
        request = RequestFactory().get('/')

        Form = block_admin.get_form(request=request)
        data = {
            'action': str(BlocklistSubmission.ACTION_ADDCHANGE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_fully_blocked.guid}\n'
            f'{self.existing_block_partially_blocked.guid}\n'
            'invalid@guid',
        }
        form = Form(data=data)
        assert form.fields['changed_version_ids'].choices == [
            (
                self.new_addon.guid,
                [
                    (
                        self.new_addon.current_version.id,
                        self.new_addon.current_version.version,
                    )
                ],
            ),
            (
                self.existing_block_partially_blocked.guid,
                [
                    (
                        self.existing_block_partially_blocked.addon.current_version.id,
                        self.existing_block_partially_blocked.addon.current_version.version,
                    )
                ],
            ),
        ]
        assert form.invalid_guids == ['invalid@guid']

        form = Form(
            data={**data, 'changed_version_ids': [self.new_addon.current_version.id]}
        )

        assert form.is_valid(), form.errors
        form.clean()  # would raise


class TestMultiDeleteForm(TestCase):
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


class TestMultiAddForm(TestCase):
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
