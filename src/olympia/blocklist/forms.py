from datetime import datetime, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.forms.widgets import HiddenInput, NumberInput

from olympia.amo.admin import HTML5DateTimeInput
from olympia.amo.forms import AMOModelForm

from .models import Block, BlocklistCannedReason, BlocklistSubmission
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


class CannedResponseWidget(forms.widgets.Select):
    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs
        )
        if instance := getattr(value, 'instance', None):
            option['attrs'] = {
                **(option.get('attrs') or {}),
                'text': instance.canned_reason,
            }
        return option


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
    # Note we don't render the widget - we manually create the checkboxes in
    # enhanced_blocks.html
    changed_version_ids = forms.fields.TypedMultipleChoiceField(
        choices=(), coerce=int, required=False
    )
    update_reason_value = forms.fields.BooleanField(required=False, initial=True)
    update_url_value = forms.fields.BooleanField(required=False, initial=True)
    canned_reasons = forms.ModelChoiceField(
        required=False,
        queryset=BlocklistCannedReason.objects.all(),
        widget=CannedResponseWidget,
    )

    def __init__(self, data=None, *args, **kw):
        instance = kw.get('instance')
        self.is_add_change = self.get_value(
            instance, data, kw, 'action', str(BlocklistSubmission.ACTION_ADDCHANGE)
        ) == str(BlocklistSubmission.ACTION_ADDCHANGE)
        input_guids = self.get_value(instance, data, kw, 'input_guids', '')

        super().__init__(data, *args, **kw)

        load_full_objects = len(splitlines(input_guids)) <= GUID_FULL_LOAD_LIMIT

        if not instance:
            self.fields['input_guids'].widget = HiddenInput()
            self.fields['action'].widget = HiddenInput()
            self.fields['delayed_until'].widget = HiddenInput()

        if (
            not instance
            or instance.signoff_state != BlocklistSubmission.SIGNOFF_PUBLISHED
        ):
            objects = BlocklistSubmission.process_input_guids(
                input_guids,
                load_full_objects=load_full_objects,
                filter_existing=self.is_add_change,
            )
            objects['total_adu'] = sum(block.current_adu for block in objects['blocks'])
            self.initial = self.initial or {}

            if changed_version_ids_field := self.fields.get('changed_version_ids'):
                self.setup_changed_version_ids_field(
                    changed_version_ids_field,
                    objects['blocks'],
                    self.is_add_change,
                    data,
                )
            for field_name in ('reason', 'url'):
                values = {
                    getattr(block, field_name, '')
                    for block in objects['blocks']
                    if block.id
                }
                update_field_name = f'update_{field_name}_value'
                if len(values) == 1 and (value := tuple(values)[0]):
                    # if there's just one existing value, prefill the field
                    self.initial[field_name] = value
                elif len(values) > 1:
                    # If the field has multiple existing values, default to not changing
                    self.initial[update_field_name] = False

            for key, value in objects.items():
                setattr(self, key, value)
        elif instance:
            self.blocks = instance.get_blocks_submitted(
                load_full_objects_threshold=GUID_FULL_LOAD_LIMIT
            )
            if load_full_objects:
                # if it's less than the limit we loaded full Block instances
                # so preload the addon_versions so the review links are
                # generated efficiently.
                Block.preload_addon_versions(self.blocks)

    def setup_changed_version_ids_field(self, field, blocks, is_add_change, data):
        field.choices = [
            (
                block.guid,
                [
                    (version.id, version.version)
                    for version in block.addon_versions
                    # ^ is XOR
                    # - for add action it allows the version when it is NOT blocked
                    # - for delete action it allows the version when it IS blocked
                    if (version.is_blocked ^ is_add_change)
                    and not version.blocklist_submission_id
                ],
            )
            for block in blocks
        ]

        self.changed_version_ids_choices = [
            v_id for _guid, opts in field.choices for (v_id, _text) in opts
        ]
        if not data and 'changed_version_ids' not in (self.initial or {}):
            # preselect all the options
            self.initial['changed_version_ids'] = self.changed_version_ids_choices

    def get_value(self, instance, data, kw, field_name, default):
        return (
            getattr(instance, field_name, default)
            if instance
            else (
                (data or {}).get(field_name)
                or (kw.get('initial') or {}).get(field_name, default)
            )
        )

    def clean_changed_version_ids(self):
        data = self.cleaned_data.get('changed_version_ids', [])
        errors = []
        # we're checking new blocks for add/change; and all blocks for delete
        for block in (bl for bl in self.blocks if not bl.id or not self.is_add_change):
            version_ids = [v.id for v in block.addon_versions]
            changed_ids = (v_id for v_id in data if v_id in version_ids)
            blocked_ids = (v.id for v in block.addon_versions if v.is_blocked)
            # for add/change we raise if there are no changed ids for this addon
            # for delete, only if there is also at least one existing blocked version
            if (self.is_add_change or any(blocked_ids)) and not any(changed_ids):
                errors.append(ValidationError(f'{block.guid} has no changed versions'))

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
