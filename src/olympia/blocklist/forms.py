from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from olympia.addons.models import Addon

from .models import Block, BlockSubmission
from .utils import splitlines


class MultiGUIDInputForm(forms.Form):
    guids = forms.CharField(
        widget=forms.Textarea(attrs={
            'cols': '80', 'rows': '10', 'required wrap': 'off'}))


class MultiDeleteForm(MultiGUIDInputForm):
    existing_block_qs = None

    def clean(self):
        guids = splitlines(self.cleaned_data.get('guids'))
        if len(guids) >= 1:
            # Note: we retrieve a full queryset here because we later need one
            # to pass to admin.actions.delete_selected in delete_multiple_view.
            self.existing_block_qs = Block.objects.filter(guid__in=guids)
            matching_guids = [block.guid for block in self.existing_block_qs]
            missing_guids = [
                guid for guid in guids if guid not in matching_guids]
            if missing_guids:
                raise ValidationError(
                    [ValidationError(
                        _('Block with GUID %(guid)s not found'),
                        params={'guid': guid})
                     for guid in missing_guids])


class MultiAddForm(MultiGUIDInputForm):
    existing_block = None

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
            if BlockSubmission.get_submissions_from_guid(guid):
                errors.append(ValidationError(
                    _('GUID %(guid)s is already in a pending BlockSubmission'),
                    params={'guid': guid}))
        if errors:
            raise ValidationError(errors)


class BlockSubmissionForm(forms.ModelForm):
    existing_min_version = forms.fields.CharField(
        widget=forms.widgets.HiddenInput, required=False)
    existing_max_version = forms.fields.CharField(
        widget=forms.widgets.HiddenInput, required=False)

    def clean(self):
        super().clean()
        guids = splitlines(self.cleaned_data.get('input_guids'))
        # Ignore for a single guid because we always update it irrespective
        # of whether it needs to be updated.
        if len(guids) > 1:
            frm_data = self.data
            # Check if the versions specified were the ones we calculated which
            # Blocks would be updated or skipped on.
            # TODO: make this more intelligent and don't force a refresh when
            # we have multiple new Blocks (but no existing blocks to update)
            versions_changed = (
                frm_data['min_version'] != frm_data['existing_min_version'] or
                frm_data['max_version'] != frm_data['existing_max_version'])
            if versions_changed:
                raise ValidationError(
                    _('Blocks to be updated may be different because Min or '
                      'Max version has changed.'))
