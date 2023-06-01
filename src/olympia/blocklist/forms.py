from datetime import datetime, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from olympia.amo.admin import HTML5DateTimeInput
from olympia.amo.forms import AMOModelForm

from .models import Block, BlocklistSubmission
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
            ValidationError(
                _('Block with GUID %(guid)s not found'), params={'guid': guid}
            )
            for guid in missing_guids
        ]

        if errors:
            raise ValidationError(errors)


class MultiAddForm(MultiGUIDInputForm):
    def clean(self):
        guids = splitlines(self.cleaned_data.get('guids'))

        errors = []
        if len(guids) == 1:
            guid = guids[0]
            blk = self.existing_block = Block.objects.filter(guid=guid).first()
            if not blk and not Block.get_addons_for_guids_qs((guid,)).exists():
                errors.append(
                    ValidationError(
                        _('Add-on with GUID %(guid)s does not exist'),
                        params={'guid': guid},
                    )
                )

        if errors:
            raise ValidationError(errors)


def _get_version_choices(blocks, ver_filter=lambda v: True):
    return [
        (
            block.guid,
            [
                (version.id, version.version)
                for version in block.addon_versions
                if ver_filter(version)
            ],
        )
        for block in blocks
    ]


class BlocklistSubmissionForm(AMOModelForm):
    delay_days = forms.fields.IntegerField(
        widget=forms.widgets.NumberInput,
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
    changed_version_ids = forms.fields.TypedMultipleChoiceField(choices=(), coerce=int)

    def __init__(self, data=None, *args, **kw):
        instance = kw.get('instance')

        def get_value(field_name, default):
            return (
                getattr(instance, field_name, default)
                if instance
                else (
                    (data or {}).get(field_name)
                    or (kw.get('initial') or {}).get(field_name, default)
                )
            )

        is_add_change = get_value(
            'action', str(BlocklistSubmission.ACTION_ADDCHANGE)
        ) == str(BlocklistSubmission.ACTION_ADDCHANGE)
        input_guids = get_value('input_guids', '')
        super().__init__(data, *args, **kw)

        load_full_objects = len(splitlines(input_guids)) <= GUID_FULL_LOAD_LIMIT

        if (
            not instance
            or instance.signoff_state != BlocklistSubmission.SIGNOFF_PUBLISHED
        ):
            objects = BlocklistSubmission.process_input_guids(
                input_guids,
                load_full_objects=load_full_objects,
                filter_existing=is_add_change,
            )
            if load_full_objects:
                Block.preload_addon_versions(objects['blocks'])
            objects['total_adu'] = sum(block.current_adu for block in objects['blocks'])

            if changed_version_ids_field := self.fields.get('changed_version_ids'):
                changed_version_ids_field.choices = _get_version_choices(
                    objects['blocks'],
                    lambda v: (v.is_blocked ^ is_add_change)
                    and not v.blocklist_submission_id,
                )
                if not data and 'changed_version_ids' not in (self.initial or {}):
                    # preselect all the options
                    flattened_choices = [
                        v_id
                        for _guid, opts in changed_version_ids_field.choices
                        for (v_id, _text) in opts
                    ]
                    self.initial = {
                        **(self.initial or {}),
                        'changed_version_ids': flattened_choices,
                    }
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

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if delay_days := data.get('delay_days', 0):
            data['delayed_until'] = datetime.now() + timedelta(days=delay_days)
