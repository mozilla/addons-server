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
            if BlockSubmission.get_submission_from_guid(guid):
                errors.append(ValidationError(
                    _('GUID %(guid)s is already in pending BlockSubmission'),
                    params={'guid': guid}))
        if errors:
            raise ValidationError(errors)
