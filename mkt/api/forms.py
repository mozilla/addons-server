from django import forms

import happyforms

from files.models import FileUpload
from mkt.submit.forms import AppDetailsBasicForm
from addons.forms import AddonFormBase


class UploadForm(happyforms.Form):
    manifest = forms.CharField(max_length=32, min_length=32)

    def clean_manifest(self):
        uuid = self.cleaned_data.get('manifest')
        try:
            upload = FileUpload.objects.get(uuid=uuid)
        except FileUpload.DoesNotExist:
            raise forms.ValidationError('No upload found.')
        if not upload.valid:
            raise forms.ValidationError('Upload not valid.')

        self.obj = upload
        return uuid
