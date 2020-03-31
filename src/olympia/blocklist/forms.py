from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from olympia.addons.models import Addon

from .models import Block, BlocklistSubmission
from .utils import splitlines


class MultiGUIDInputForm(forms.Form):
    existing_block = None

    guids = forms.CharField(
        widget=forms.Textarea(attrs={
            'cols': '80', 'rows': '10', 'required wrap': 'off'}))


class MultiDeleteForm(MultiGUIDInputForm):

    def clean(self):
        guids = splitlines(self.cleaned_data.get('guids'))
        errors = []
        if len(guids) >= 1:
            qs = Block.objects.filter(guid__in=guids)
            matching_guids = list(qs.values_list('guid', flat=True))
            missing_guids = [
                guid for guid in guids if guid not in matching_guids]
            if missing_guids:
                errors.append(
                    [ValidationError(
                        _('Block with GUID %(guid)s not found'),
                        params={'guid': guid})
                     for guid in missing_guids])
            for guid in matching_guids:
                if BlocklistSubmission.get_submissions_from_guid(guid):
                    errors.append(ValidationError(
                        _('GUID %(guid)s is in a pending Submission'),
                        params={'guid': guid}))
        if errors:
            raise ValidationError(errors)


class MultiAddForm(MultiGUIDInputForm):

    def clean(self):
        guids = splitlines(self.cleaned_data.get('guids'))
        errors = []
        if len(guids) == 1:
            guid = guids[0]
            blk = self.existing_block = Block.objects.filter(guid=guid).first()
            if not blk and not Addon.unfiltered.filter(guid=guid).exists():
                errors.append(ValidationError(
                    _('Addon with GUID %(guid)s does not exist'),
                    params={'guid': guid}))
        for guid in guids:
            if BlocklistSubmission.get_submissions_from_guid(guid):
                errors.append(ValidationError(
                    _('GUID %(guid)s is already in a pending Submission'),
                    params={'guid': guid}))
        if errors:
            raise ValidationError(errors)


class BlocklistSubmissionForm(forms.ModelForm):
    existing_min_version = forms.fields.CharField(
        widget=forms.widgets.HiddenInput, required=False)
    existing_max_version = forms.fields.CharField(
        widget=forms.widgets.HiddenInput, required=False)

    def _check_if_existing_blocks_changed(self, all_guids, v_min, v_max,
                                          existing_v_min, existing_v_max):
        # shortcut if the min/max versions havn't changed
        if v_min == existing_v_min and v_max == existing_v_max:
            return False

        block_data = list(Block.objects.filter(guid__in=all_guids).values_list(
            'guid', 'min_version', 'max_version'))

        to_update_based_on_existing_v = [
            guid for (guid, min_version, max_version) in block_data
            if not (
                min_version == existing_v_min and
                max_version == existing_v_max)]
        to_update_based_on_new_v = [
            guid for (guid, min_version, max_version) in block_data
            if not (min_version == v_min and max_version == v_max)]

        return to_update_based_on_existing_v != to_update_based_on_new_v

    def clean(self):
        super().clean()
        data = self.cleaned_data
        guids = splitlines(data.get('input_guids'))
        # Ignore for a single guid because we always update it irrespective of
        # whether it needs to be updated.
        is_addchange_submission = (
            data.get('action', BlocklistSubmission.ACTION_ADDCHANGE) ==
            BlocklistSubmission.ACTION_ADDCHANGE)
        if len(guids) > 1 and is_addchange_submission:
            blocks_have_changed = self._check_if_existing_blocks_changed(
                guids,
                data.get('min_version'),
                data.get('max_version'),
                data.get('existing_min_version'),
                data.get('existing_max_version'))
            if blocks_have_changed:
                raise ValidationError(
                    _('Blocks to be updated are different because Min or '
                      'Max version has changed.'))
