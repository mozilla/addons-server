import base64
import json
import StringIO

from django import forms

import happyforms

from addons.models import Addon, Category
import amo
from files.models import FileUpload
from mkt.developers.utils import check_upload


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


class JSONField(forms.Field):
    def to_python(self, value):
        if value == '':
            return None

        try:
            if isinstance(value, basestring):
                return json.loads(value)
        except ValueError:
            pass
        return value


class PreviewJSONForm(happyforms.Form):
    file = JSONField(required=True)
    position = forms.IntegerField(required=True)

    def clean_file(self):
        file_ = self.cleaned_data.get('file', {})
        try:
            if not set(['data', 'type']).issubset(set(file_.keys())):
                raise forms.ValidationError('Type and data are required.')
        except AttributeError:
            raise forms.ValidationError('File must be a dictionary.')

        file_obj = StringIO.StringIO(base64.b64decode(file_['data']))
        errors, hash_ = check_upload(file_obj, 'graphic', file_['type'])
        if errors:
            raise forms.ValidationError(errors)

        self.hash_ = hash_
        return file_

    def clean(self):
        self.cleaned_data['upload_hash'] = getattr(self, 'hash_', None)
        return self.cleaned_data


class CategoryForm(happyforms.Form):
    # The CategoryFormSet is far too complicated, I don't follow it.
    # Hopefully this is easier.
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.filter(type=amo.ADDON_WEBAPP))


class StatusForm(happyforms.ModelForm):
    status = forms.ChoiceField(choices=(), required=False)

    lookup = {
        # You can push to the pending queue.
        amo.STATUS_NULL: amo.STATUS_PENDING,
        # You can push to public if you've been reviewed.
        amo.STATUS_PUBLIC_WAITING: amo.STATUS_PUBLIC,
    }

    class Meta:
        model = Addon
        fields = ['status', 'disabled_by_user']

    def __init__(self, *args, **kw):
        super(StatusForm, self).__init__(*args, **kw)
        choice = self.lookup.get(self.instance.status)
        choices = []
        if self.instance.status in self.lookup:
            choices.append(amo.STATUS_CHOICES_API[choice])
        choices.append(amo.STATUS_CHOICES_API[self.instance.status])
        self.fields['status'].choices = [(k, k) for k in sorted(choices)]

    def clean_status(self):
        requested = self.cleaned_data['status']
        if requested == amo.STATUS_CHOICES_API[amo.STATUS_PENDING]:
            valid, reasons = self.instance.is_complete()
            if not valid:
                raise forms.ValidationError(reasons)
        return amo.STATUS_CHOICES_API_LOOKUP[requested]
