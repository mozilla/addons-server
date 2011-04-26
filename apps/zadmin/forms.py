from django import forms
from django.db import connection

import happyforms
from tower import ugettext_lazy as _lazy

import amo
from amo.urlresolvers import reverse
from applications.models import Application, AppVersion
from zadmin.models import ValidationJob, ValidationResult


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

    def save(self):
        job = super(BulkValidationForm, self).save()
        sql = """
            select files.id
            from files
            join versions v on v.id=files.version_id
            join versions_summary vs on vs.version_id=v.id
            where
                vs.application_id = %(application_id)s
                and vs.max = %(curr_max_version)s
                and files.status in %(file_status)s"""
        cursor = connection.cursor()
        cursor.execute(sql, {'application_id': job.application.id,
                             'curr_max_version': job.curr_max_version.id,
                             'file_status': [amo.STATUS_LISTED,
                                             amo.STATUS_PUBLIC]})
        for row in cursor:
            # TODO(Kumar) queue up the task to validate in the background.
            # Task should create validation when complete:
            #   file_id = row[0]
            #   fv = FileValidation.from_json(validation)
            ValidationResult.objects.create(validation_job=job)
        return job
