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
from olympia.reviewers.models import ReviewActionReason

from ..admin import BlocklistSubmissionAdmin
from ..forms import MultiAddForm, MultiDeleteForm
from ..models import Block, BlocklistSubmission, BlockType, BlockVersion


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
            'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
            'block_type': BlockType.BLOCKED,
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
            'action': str(BlocklistSubmission.ACTIONS.DELETE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
            'block_type': BlockType.BLOCKED,
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

    def test_changed_version_ids_choices_existing_submission(self):
        Form = self.get_form()

        # When the instance exists the choices are limited to the existing versions
        # We don't bother creating proper labels because they aren't rendered anyway
        choices = [
            (self.new_addon.current_version.id, self.new_addon.current_version.id),
            (
                self.partial_existing_addon_v_notblocked.id,
                self.partial_existing_addon_v_notblocked.id,
            ),
        ]
        submission = BlocklistSubmission.objects.create(
            input_guids=f'{self.new_addon.guid}\n{self.existing_block_partial.guid}',
        )
        for action in BlocklistSubmission.ACTIONS.values:
            # they're the same for each of the actions
            submission.update(
                action=action,
                changed_version_ids=[
                    self.new_addon.current_version.id,
                    self.partial_existing_addon_v_notblocked.id,
                ],
            )
            form = Form(instance=submission)

            assert form.fields['changed_version_ids'].choices == choices

            submission.update(changed_version_ids=[self.new_addon.current_version.id])
            form = Form(instance=submission)
            assert form.fields['changed_version_ids'].choices == [choices[0]]
            assert choices[0][0] == self.new_addon.current_version.id

    def test_changed_version_ids_widget(self):
        data = {
            'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
            'block_type': BlockType.BLOCKED,
            'changed_version_ids': [self.new_addon.current_version.id],
        }
        form = self.get_form()(data=data)
        field = form.fields['changed_version_ids']
        value = data['changed_version_ids']
        name = 'name'
        attrs = {'some_attr': 'some_attr_value'}
        flattened_choices = [
            v_id for _guid, opts in field.choices for (v_id, _text) in opts
        ]
        assert field.widget.get_context(name, value, attrs) == {
            'verb': 'Block',
            'widget': {
                'attrs': {'multiple': True, **attrs},
                'choices': flattened_choices,
                'is_hidden': False,
                'name': name,
                'optgroups': [],
                'required': False,
                'template_name': 'admin/blocklist/widgets/blocks.html',
                'value': value,
            },
            'blocks': form.blocks,
            'total_adu': sum(block.current_adu for block in form.blocks),
        }

    def test_initial_reason_and_url_values(self):
        Form = self.get_form()
        data = {
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
        }
        self.existing_block_partial.update(reason='partial reason', url='url')
        self.existing_block_full.update(reason='full reason', url='url')

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

    def test_existing_reason_and_url_values(self):
        # block metadata shouldn't make a difference
        self.existing_block_partial.update(reason='partial reason')

        Form = self.get_form()
        submission = BlocklistSubmission.objects.create(
            input_guids=f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
            url='new url',
        )

        form = Form(instance=submission)
        # for an existing submission we get initial url and reason from the instance
        assert form.initial['reason'] is None
        assert form.initial['url'] == 'new url'
        assert form.initial['update_reason_value'] is False
        assert form.initial['update_url_value'] is True

        # An empty string is still counted
        submission.update(url='')
        form = Form(instance=submission)
        assert form.initial['url'] == ''
        assert form.initial['update_url_value'] is True

    def test_new_blocks_must_have_changed_versions(self):
        Form = self.get_form()
        data = {
            'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
            'block_type': BlockType.BLOCKED,
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
        data['action'] = str(BlocklistSubmission.ACTIONS.DELETE)
        data['changed_version_ids'] = [
            self.partial_existing_addon_v_blocked.id,
            self.full_existing_addon_v1.id,
        ]
        form = Form(data=data)
        assert form.is_valid(), form.errors

    def test_duplicate_version_strings_must_all_be_changed(self):
        Form = self.get_form()
        # this version string will exist twice for this guid
        ver_string = self.partial_existing_addon_v_notblocked.version
        # create a previous addon instance that reused the same version string
        old_addon = addon_factory(version_kw={'version': ver_string})
        old_addon_version = old_addon.current_version
        old_addon.delete()
        old_addon.addonguid.update(guid=self.partial_existing_addon.guid)
        # repeat but this time the version was blocked already so not a choice
        old_blocked_addon = addon_factory(version_kw={'version': ver_string})
        old_blocked_addon_version = old_blocked_addon.current_version
        old_blocked_addon.delete()
        old_blocked_addon.addonguid.update(guid=self.partial_existing_addon.guid)
        BlockVersion.objects.create(
            version=old_blocked_addon_version, block=self.existing_block_partial
        )
        data = {
            'action': str(BlocklistSubmission.ACTIONS.ADDCHANGE),
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}',
            'block_type': BlockType.BLOCKED,
            'changed_version_ids': [
                self.new_addon.current_version.id,
            ],
        }

        # it's valid when neither of the versions are being changed
        form = Form(data=data)
        assert form.is_valid()

        # but not when only one is
        data['changed_version_ids'].append(self.partial_existing_addon_v_notblocked.id)
        form = Form(data=data)
        assert not form.is_valid()
        assert form.errors == {
            'changed_version_ids': [
                f'{self.partial_existing_addon.guid}:{ver_string} exists more than once'
                f'. All {ver_string} versions must be selected together.'
            ]
        }

        # and it's valid again if both are being changed
        data['changed_version_ids'].append(old_addon_version.id)
        form = Form(data=data)
        assert form.is_valid()

    def test_clean(self):
        Form = self.get_form()
        data = {
            'input_guids': f'{self.new_addon.guid}\n'
            f'{self.existing_block_full.guid}\n'
            f'{self.existing_block_partial.guid}\n'
            'invalid@guid',
            'block_type': BlockType.BLOCKED,
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
        a = ReviewActionReason.objects.create(name='aaa', canned_block_reason='yes')
        c = ReviewActionReason.objects.create(name='cc', canned_block_reason='noooo')
        b = ReviewActionReason.objects.create(name='b', canned_block_reason='maybe')
        ReviewActionReason.objects.create(
            name='inactive', canned_block_reason='.', is_active=False
        )
        ReviewActionReason.objects.create(
            name='empty', canned_block_reason='', canned_response='a'
        )

        form = self.get_form()(data={'input_guids': addon.guid})

        choices = list(form.fields['canned_reasons'].choices)
        assert choices == [
            (a.id, 'aaa'),
            (b.id, 'b'),
            (c.id, 'cc'),
        ]
        assert choices[0][0].instance == a
        assert choices[1][0].instance == b
        assert choices[2][0].instance == c

        render = form.fields['canned_reasons'].widget.render(
            name='canned_reasons', value=''
        )
        input = (
            '<div>\n    '
            '<label><input type="checkbox" name="canned_reasons" value="{id}" '
            'data-block-reason="{reason}">\n '
            '{name}</label>\n\n'
            '</div>'
        )
        assert render == (
            '<div>'
            + ''.join(
                input.format(id=obj.id, reason=obj.canned_block_reason, name=obj.name)
                for obj in (a, b, c)
            )
            + '\n</div>'
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
