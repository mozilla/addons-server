from django import forms

import happyforms
from tower import ugettext_lazy as _lazy

import amo
from amo.urlresolvers import reverse
from applications.models import Application, AppVersion
from zadmin.models import ValidationJob
from zadmin import tasks


class BulkValidationForm(happyforms.ModelForm):
    application = forms.ChoiceField(
                label=_lazy(u'Application'),
                choices=[(a.id, a.pretty) for a in amo.APPS_ALL.values()])
    curr_max_version = forms.ChoiceField(
                label=_lazy(u'Current Max. Version'),
                choices=[('', _lazy(u'Select an application first'))])
    target_version = forms.ChoiceField(
                label=_lazy(u'Target Version'),
                choices=[('', _lazy(u'Select an application first'))])
    finish_email = forms.CharField(required=False,
                                   label=_lazy(u'Email when finished'))

    class Meta:
        model = ValidationJob
        fields = ('application', 'curr_max_version', 'target_version',
                  'finish_email')

    def __init__(self, *args, **kw):
        super(BulkValidationForm, self).__init__(*args, **kw)
        w = self.fields['application'].widget
        # Get the URL after the urlconf has loaded.
        w.attrs['data-url'] = reverse('zadmin.application_versions_json')

    def version_choices_for_app_id(self, app_id):
        versions = AppVersion.objects.filter(application__id=app_id)
        return [(v.id, v.version) for v in versions]

    def clean_application(self):
        app_id = int(self.cleaned_data['application'])
        app = Application.objects.get(pk=app_id)
        self.cleaned_data['application'] = app
        choices = self.version_choices_for_app_id(app_id)
        self.fields['target_version'].choices = choices
        self.fields['curr_max_version'].choices = choices
        return self.cleaned_data['application']

    def _clean_appversion(self, field):
        return AppVersion.objects.get(pk=int(field))

    def clean_curr_max_version(self):
        return self._clean_appversion(self.cleaned_data['curr_max_version'])

    def clean_target_version(self):
        return self._clean_appversion(self.cleaned_data['target_version'])
