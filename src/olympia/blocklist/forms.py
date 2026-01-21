from collections import defaultdict
from datetime import datetime, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.forms.widgets import HiddenInput, NumberInput

from olympia.amo.admin import HTML5DateTimeInput
from olympia.amo.forms import AMOModelForm
from olympia.reviewers.models import ReviewActionReason

from .models import Block, BlocklistSubmission, BlockType
from .utils import splitlines


# The limit for how many GUIDs should be fully loaded with all metadata
GUID_FULL_LOAD_LIMIT = 100


class MultiGUIDInputForm(forms.Form):
    existing_block = None

    guids = forms.CharField(
        widget=forms.Textarea(
            attrs={'cols': '80', 'rows': '10', 'required wrap': 'off'}
        )
    )


class MultiDeleteForm(MultiGUIDInputForm):
    def clean(self):
        guids = splitlines(self.cleaned_data.get('guids'))
        matching = Block.objects.filter(guid__in=guids).values_list('guid', flat=True)

        missing_guids = (guid for guid in guids if guid not in matching)
        errors = [
            ValidationError(f'Block with GUID {guid} not found')
            for guid in missing_guids
        ]

        if errors:
            raise ValidationError(errors)


class MultiAddForm(MultiGUIDInputForm):
    def clean(self):
        guids = splitlines(self.cleaned_data.get('guids'))

        if len(guids) == 1:
            guid = guids[0]
            blk = self.existing_block = Block.objects.filter(guid=guid).first()
            if not blk and not Block.get_addons_for_guids_qs((guid,)).exists():
                raise ValidationError(f'Add-on with GUID {guid} does not exist')


class CannedResponseWidget(forms.widgets.CheckboxSelectMultiple):
    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        if instance := getattr(value, 'instance', None):
            option['attrs'] = {
                **(option.get('attrs') or {}),
                'data-block-reason': instance.canned_block_reason,
            }
        return option


class BlocksWidget(forms.widgets.SelectMultiple):
    """Custom widget that renders a template snippet with all the guids and versions,
    rather than just checkboxes for the valid choices"""

    template_name = 'admin/blocklist/widgets/blocks.html'

    def optgroups(self, name, value, attrs=None):
        return []

    def get_verb(self, action):
        """Return the verb to use when displaying a given version, depending
        on the action."""
        try:
            verb = BlocklistSubmission.ACTIONS(action).short
        except KeyError:
            verb = '?'
        return verb

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        return {
            **context,
            'widget': {
                **context.get('widget', {}),
                'choices': self.choices,
                'value': value,
            },
            'blocks': self.blocks,
            'total_adu': sum(block.current_adu for block in self.blocks),
            'verb': self.get_verb(self.action),
        }


class BlocklistSubmissionForm(AMOModelForm):
    delay_days = forms.fields.IntegerField(
        widget=NumberInput,
        initial=0,
        label='Delay Block by days',
        required=False,
        min_value=0,
    )
    delayed_until = forms.fields.DateTimeField(
        widget=HTML5DateTimeInput, required=False
    )
    changed_version_ids = forms.fields.TypedMultipleChoiceField(
        choices=(),
        coerce=int,
        required=False,
        widget=BlocksWidget,
    )
    update_reason_value = forms.fields.BooleanField(required=False, initial=True)
    update_url_value = forms.fields.BooleanField(required=False, initial=True)
    canned_reasons = forms.ModelMultipleChoiceField(
        required=False,
        queryset=ReviewActionReason.objects.filter(
            is_active=True,
        ).exclude(canned_block_reason=''),
        widget=CannedResponseWidget,
    )

    def __init__(self, data=None, *args, **kw):
        super().__init__(data, *args, **kw)

        self.action = int(
            self.get_value('action', BlocklistSubmission.ACTIONS.ADDCHANGE)
        )
        self.is_add_change = self.action == BlocklistSubmission.ACTIONS.ADDCHANGE
        input_guids = self.get_value('input_guids', '')
        load_full_objects = len(splitlines(input_guids)) <= GUID_FULL_LOAD_LIMIT
        is_published = (
            self.instance.signoff_state == BlocklistSubmission.SIGNOFF_STATES.PUBLISHED
        )

        if not self.instance.id:
            self.fields['input_guids'].widget = HiddenInput()
            self.fields['action'].widget = HiddenInput()
            self.fields['delayed_until'].widget = HiddenInput()
            if self.action in (
                BlocklistSubmission.ACTIONS.HARDEN,
                BlocklistSubmission.ACTIONS.SOFTEN,
            ):
                # When softening/hardening, the widget needs to be present for
                # us to record the block type on the blocklistsubmission, but
                # we're hiding it and forcing the value depending on the action
                # to make the UI less confusing.
                block_type = (
                    BlockType.BLOCKED
                    if self.action == BlocklistSubmission.ACTIONS.HARDEN
                    else BlockType.SOFT_BLOCKED
                )
                self.fields['block_type'].widget = HiddenInput()
                self.fields['block_type'].choices = (
                    (block_type, dict(BlockType.choices)[block_type]),
                )
                self.fields['block_type'].initial = block_type
                self.fields['block_type'].label = ''

        objects = BlocklistSubmission.process_input_guids(
            input_guids,
            load_full_objects=load_full_objects,
            filter_existing=self.is_add_change and not is_published,
        )
        for key, value in objects.items():
            setattr(self, key, value)

        if changed_version_ids_field := self.fields.get('changed_version_ids'):
            self.setup_changed_version_ids_field(changed_version_ids_field, data)

        for field_name in ('reason', 'url'):
            update_field_name = f'update_{field_name}_value'
            if not self.instance.id:
                values = {
                    getattr(block, field_name, '') for block in self.blocks if block.id
                }
                if len(values) == 1 and (value := tuple(values)[0]):
                    # if there's just one existing value, prefill the field
                    self.initial[field_name] = value
                elif len(values) > 1:
                    # If the field has multiple existing values, default to not changing
                    self.initial[update_field_name] = False
            else:
                self.initial[update_field_name] = (
                    getattr(self.instance, field_name) is not None
                )

    def should_version_be_available_for_action(self, version):
        """Return whether or not the given version should be available as a
        choice for the action we're currently doing."""
        conditions = {
            BlocklistSubmission.ACTIONS.ADDCHANGE: not version.is_blocked,
            BlocklistSubmission.ACTIONS.DELETE: version.is_blocked,
            BlocklistSubmission.ACTIONS.HARDEN: (
                version.is_blocked
                and version.blockversion.block_type == BlockType.SOFT_BLOCKED
            ),
            BlocklistSubmission.ACTIONS.SOFTEN: (
                version.is_blocked
                and version.blockversion.block_type == BlockType.BLOCKED
            ),
        }
        return conditions.get(self.action)

    def setup_changed_version_ids_field(self, field, data):
        if not self.instance.id:
            field.choices = [
                (
                    block.guid,
                    [
                        (version.id, version.version)
                        for version in block.addon_versions
                        if self.should_version_be_available_for_action(version)
                        and not version.blocklist_submission_id
                    ],
                )
                for block in self.blocks
            ]

            self.changed_version_ids_choices = [
                v_id for _guid, opts in field.choices for (v_id, _text) in opts
            ]
            if not data and not self.initial.get('changed_version_ids'):
                # preselect all the options
                self.initial['changed_version_ids'] = self.changed_version_ids_choices
        else:
            field.choices = list(
                (v_id, v_id) for v_id in self.instance.changed_version_ids
            )
            self.changed_version_ids_choices = self.instance.changed_version_ids
        field.widget.choices = self.changed_version_ids_choices
        field.widget.blocks = self.blocks
        field.widget.action = self.action

    def get_value(self, field_name, default):
        return (
            getattr(self.instance, field_name, default)
            if self.instance.id
            else self.data.get(field_name, self.initial.get(field_name, default))
        )

    def clean_changed_version_ids(self):
        data = self.cleaned_data.get('changed_version_ids', [])
        errors = []

        # First, check we're not creating empty blocks
        # we're checking new blocks for add/change; and all blocks for other actions
        for block in (bl for bl in self.blocks if not bl.id or not self.is_add_change):
            version_ids = [v.id for v in block.addon_versions]
            changed_ids = (v_id for v_id in data if v_id in version_ids)
            blocked_ids = (v.id for v in block.addon_versions if v.is_blocked)
            # for add/change we raise if there are no changed ids for this addon
            # for other actions, only if there is also at least one existing blocked
            # version
            if (self.is_add_change or any(blocked_ids)) and not any(changed_ids):
                errors.append(ValidationError(f'{block.guid} has no changed versions'))

        # Second, check for duplicate version strings in reused guids.
        error_string = (
            '{}:{} exists more than once. All {} versions must be selected together.'
        )
        for block in self.blocks:
            version_strs = defaultdict(set)  # collect version strings together
            for version in block.addon_versions:
                if version.id in self.changed_version_ids_choices:
                    version_strs[version.version].add(version.id)
            for version_str, ids in version_strs.items():
                # i.e. dupe version string & some ids, but not all, are being changed.
                if len(ids) > 1 and not ids.isdisjoint(data) and not ids.issubset(data):
                    errors.append(
                        ValidationError(
                            error_string.format(block.guid, version_str, version_str)
                        )
                    )

        if errors:
            raise ValidationError(errors)
        return data

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if delay_days := data.get('delay_days', 0):
            data['delayed_until'] = datetime.now() + timedelta(days=delay_days)
        for field_name in ('reason', 'url'):
            if not data.get(f'update_{field_name}_value'):
                data[field_name] = None
            elif field_name in data and data[field_name] is None:
                data[field_name] = ''
