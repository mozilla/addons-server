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
from olympia.blocklist.models import Block, BlocklistCannedReason, BlocklistSubmission


class TestBlocklistSubmissionForm(TestCase):
    def setUp(self):
        self.user = user_factory()
        self.new_addon = addon_factory(
            guid='any@new', average_daily_users=100, version_kw={'version': '5.56'}
        )
        self.another_new_addon = addon_factory(
            guid='another@new',
            average_daily_users=100000,
        )

        self.full_existing_addon = addon_factory(guid='full@existing')
        self.full_existing_addon_v1 = self.full_existing_addon.current_version
        self.full_existing_addon_v2 = version_factory(addon=self.full_existing_addon)
        self.existing_block_full = block_factory(
            addon=self.full_existing_addon,
            updated_by=self.user,
        )

        self.partial_existing_addon = addon_factory(
            guid='partial@existing',
            average_daily_users=99,
        )
        self.partial_existing_addon_v_blocked = (
            self.partial_existing_addon.current_version
        )
        self.existing_block_partial = block_factory(
            addon=self.partial_existing_addon,
            updated_by=self.user,
        )
        self.partial_existing_addon_v_notblocked = version_factory(
            addon=self.partial_existing_addon
        )

    def get_form(self):
        block_admin = BlocklistSubmissionAdmin(
            model=BlocklistSubmission, admin_site=admin_site
        )
        request = RequestFactory().get('/')
        request.user = self.user
        return block_admin.get_form(request=request)

    def test_changed_version_ids_choices_add_action(self):
        data = {
            'action': str(BlocklistSubmission.ACTION_ADDCHANGE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
        }
        Form = self.get_form()
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
                self.existing_block_partial.guid,
                [
                    (
                        self.partial_existing_addon_v_notblocked.id,
                        self.partial_existing_addon_v_notblocked.version,
                    )
                ],
            ),
        ]
        assert form.invalid_guids == ['invalid@guid']

        form = Form(
            data={**data, 'changed_version_ids': [self.new_addon.current_version.id]}
        )
        assert form.is_valid(), form.errors
        assert not form.errors

        form = Form(
            data={
                **data,
                'changed_version_ids': [self.partial_existing_addon_v_blocked.id],
            }
        )
        assert not form.is_valid()
        assert form.errors == {
            'changed_version_ids': [
                f'Select a valid choice. {self.partial_existing_addon_v_blocked.id} is '
                'not one of the available choices.'
            ]
        }

    def test_changed_version_ids_choices_delete_action(self):
        Form = self.get_form()
        data = {
            'action': str(BlocklistSubmission.ACTION_DELETE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
        }
        form = Form(data=data)
        assert form.fields['changed_version_ids'].choices == [
            (
                self.existing_block_full.guid,
                [
                    (
                        self.full_existing_addon_v1.id,
                        self.full_existing_addon_v1.version,
                    ),
                    (
                        self.full_existing_addon_v2.id,
                        self.full_existing_addon_v2.version,
                    ),
                ],
            ),
            (self.new_addon.guid, []),
            (
                self.existing_block_partial.guid,
                [
                    (
                        self.partial_existing_addon_v_blocked.id,
                        self.partial_existing_addon_v_blocked.version,
                    )
                ],
            ),
        ]
        assert form.invalid_guids == ['invalid@guid']

        form = Form(
            data={
                **data,
                'changed_version_ids': [
                    self.partial_existing_addon_v_blocked.id,
                    self.full_existing_addon_v1.id,
                ],
            }
        )
        assert form.is_valid(), form.errors
        assert not form.errors

        form = Form(
            data={**data, 'changed_version_ids': [self.new_addon.current_version.id]}
        )
        assert not form.is_valid()
        assert form.errors == {
            'changed_version_ids': [
                f'Select a valid choice. {self.new_addon.current_version.id} is not '
                'one of the available choices.'
            ]
        }

    def test_initial_reason_and_url_values(self):
        Form = self.get_form()
        data = {
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
        }
        self.existing_block_partial.update(reason='partial reason')
        self.existing_block_full.update(reason='full reason')
        self.existing_block_partial.update(url='url')
        self.existing_block_full.update(url='url')

        form = Form(initial=data)
        # when we just have a single existing block we default to the existing values
        # (existing_block_full is ignored entirely because won't be updated)
        assert form.initial['reason'] == 'partial reason'
        assert form.initial['url'] == 'url'
        assert 'update_url_value' not in form.initial
        assert 'update_reason_value' not in form.initial

        # lets make existing_block_full not fully blocked
        self.full_existing_addon_v2.blockversion.delete()
        form = Form(initial=data)
        assert 'reason' not in form.initial  # two values so not default
        assert form.initial['url'] == 'url'  # both the same, so we can default
        assert 'update_url_value' not in form.initial
        assert form.initial['update_reason_value'] is False  # checkbox defaults false

    def test_new_blocks_must_have_changed_versions(self):
        Form = self.get_form()
        data = {
            'action': str(BlocklistSubmission.ACTION_ADDCHANGE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
            # only one version selected
            'changed_version_ids': [self.partial_existing_addon_v_notblocked.id],
        }
        form = Form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            # only new_addon is an error- existing blocks can just have metadata changes
            'changed_version_ids': [f'{self.new_addon.guid} has no changed versions']
        }

        # delete action is similar, but we allow deleting a block with no versions
        Block.objects.create(addon=self.new_addon, updated_by=self.user)
        data['action'] = str(BlocklistSubmission.ACTION_DELETE)
        data['changed_version_ids'] = [
            self.partial_existing_addon_v_blocked.id,
            self.full_existing_addon_v1.id,
        ]
        form = Form(data=data)
        assert form.is_valid(), form.errors

    def test_clean(self):
        Form = self.get_form()
        data = {
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
            'url': 'new url',
            'update_url_value': False,
            'reason': 'new reason',
            # no update_reason_value
            'changed_version_ids': [self.new_addon.current_version.id],
        }
        form = Form(data=data)
        form.is_valid()
        # if update_xxx_value is False or mising the value will be ignored
        assert form.cleaned_data['url'] is None
        assert form.cleaned_data['reason'] is None

        data['url'] = None
        data['update_url_value'] = True
        data['update_reason_value'] = True
        form = Form(data=data)
        form.is_valid()
        # if update_xxx_value is True a value should be set, even if None in data
        assert form.cleaned_data['url'] == ''
        assert form.cleaned_data['reason'] == 'new reason'

    def test_canned_reasons(self):
        addon = addon_factory()
        a = BlocklistCannedReason.objects.create(name='aaa', canned_reason='yes')
        c = BlocklistCannedReason.objects.create(name='cc', canned_reason='noooo')
        b = BlocklistCannedReason.objects.create(name='b', canned_reason='maybe')

        form = self.get_form()(data={'input_guids': addon.guid})

        choices = list(form.fields['canned_reasons'].choices)
        assert choices == [
            ('', '---------'),
            (a.id, 'aaa'),
            (b.id, 'b'),
            (c.id, 'cc'),
        ]
        assert choices[1][0].instance == a
        assert choices[2][0].instance == b
        assert choices[3][0].instance == c

        render = form.fields['canned_reasons'].widget.render(
            name='canned_reasons', value=''
        )
        assert render == (
            '<select name="canned_reasons">\n'
            '  <option value="" selected>---------</option>\n\n'
            f'  <option value="{a.id}" text="{a.canned_reason}">{a.name}</option>\n\n'
            f'  <option value="{b.id}" text="{b.canned_reason}">{b.name}</option>\n\n'
            f'  <option value="{c.id}" text="{c.canned_reason}">{c.name}</option>\n\n'
            '</select>'
        )


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
