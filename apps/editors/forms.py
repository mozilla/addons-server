from datetime import timedelta

from django import forms
from django.forms import widgets
from django.db.models import Q
from django.utils.translation import get_language
from django.core.validators import ValidationError

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo.urlresolvers import reverse
from applications.models import AppVersion


from editors.models import CannedResponse
from editors.helpers import ReviewHelper, ReviewAddon, ReviewFiles
from files.models import File


ACTION_FILTERS = (('', ''), ('approved', _lazy('Approved reviews')),
                  ('deleted', _lazy('Deleted reviews')))

ACTION_DICT = dict(approved=amo.LOG.APPROVE_REVIEW,
                   deleted=amo.LOG.DELETE_REVIEW)


class EventLogForm(happyforms.Form):
    start = forms.DateField(required=False,
                            label=_lazy(u'View entries between'))
    end = forms.DateField(required=False,
                          label=_lazy(u'and'))
    filter = forms.ChoiceField(required=False, choices=ACTION_FILTERS,
                               label=_lazy(u'Filter by type/action'))

    def clean(self):
        data = self.cleaned_data
        # We want this to be inclusive of the end date.
        if data['end']:
            data['end'] += timedelta(days=1)

        if data['filter']:
            data['filter'] = ACTION_DICT[data['filter']]
        return data


class ReviewLogForm(happyforms.Form):
    start = forms.DateField(required=False,
                            label=_lazy(u'View entries between'))
    end = forms.DateField(required=False,
                          label=_lazy(u'and'))

    def clean(self):
        data = self.cleaned_data
        # We want this to be inclusive of the end date.
        if data['end']:
            data['end'] += timedelta(days=1)

        return data


class QueueSearchForm(happyforms.Form):
    text_query = forms.CharField(
                    required=False,
                    label=_lazy(u'Search by add-on name / author email'))
    admin_review = forms.ChoiceField(required=False,
                                     choices=[('', ''),
                                              ('1', _lazy(u'yes')),
                                              ('0', _lazy(u'no'))],
                                     label=_lazy(u'Admin Flag'))
    application_id = forms.ChoiceField(
                required=False,
                label=_lazy(u'Application'),
                choices=([('', '')] +
                         [(a.id, a.pretty) for a in amo.APPS_ALL.values()]))
    max_version = forms.ChoiceField(
                required=False,
                label=_lazy(u'Max. Version'),
                choices=[('', _lazy(u'Select an application first'))])
    waiting_time_days = forms.ChoiceField(
                required=False,
                label=_lazy(u'Days Since Submission'),
                choices=([('', '')] +
                         [(i, i) for i in range(1, 10)] + [('10+', '10+')]))
    addon_type_ids = forms.MultipleChoiceField(
                required=False,
                label=_lazy(u'Add-on Types'),
                choices=((id, tp) for id, tp in amo.ADDON_TYPES.items()))
    platform_ids = forms.MultipleChoiceField(
                required=False,
                label=_lazy(u'Platforms'),
                choices=[(p.id, p.name)
                         for p in amo.PLATFORMS.values()
                         if p not in (amo.PLATFORM_ANY, amo.PLATFORM_ALL)])

    def __init__(self, *args, **kw):
        super(QueueSearchForm, self).__init__(*args, **kw)
        w = self.fields['application_id'].widget
        # Get the URL after the urlconf has loaded.
        w.attrs['data-url'] = reverse('editors.application_versions_json')

    def version_choices_for_app_id(self, app_id):
        versions = AppVersion.objects.filter(application__id=app_id)
        return [('', '')] + [(v.version, v.version) for v in versions]

    def clean_application_id(self):
        if self.cleaned_data['application_id']:
            choices = self.version_choices_for_app_id(
                                        self.cleaned_data['application_id'])
            self.fields['max_version'].choices = choices
        return self.cleaned_data['application_id']

    def clean_max_version(self):
        if self.cleaned_data['max_version']:
            if not self.cleaned_data['application_id']:
                raise forms.ValidationError("No application selected")
        return self.cleaned_data['max_version']

    def filter_qs(self, qs):
        data = self.cleaned_data
        if data['admin_review']:
            qs = qs.filter(admin_review=data['admin_review'])
        if data['addon_type_ids']:
            qs = qs.filter_raw('addon_type_id IN', data['addon_type_ids'])
        if data['application_id']:
            qs = qs.filter_raw('apps.application_id =', data['application_id'])
            if data['max_version']:
                joins = [
                    'JOIN versions_summary vs ON (versions.id = vs.version_id)',
                    'JOIN appversions max_version on (max_version.id = vs.max)']
                qs.base_query['from'].extend(joins)
                qs = qs.filter_raw('max_version.version =', data['max_version'])
        if data['platform_ids']:
            qs = qs.filter_raw('files.platform_id IN', data['platform_ids'])
            # Adjust _file_platform_ids so that it includes ALL platforms
            # not the ones filtered by the search criteria:
            qs.base_query['from'].extend([
                """LEFT JOIN files all_files
                   ON (all_files.version_id = versions.id)"""])
            group = 'GROUP_CONCAT(DISTINCT all_files.platform_id)'
            qs.base_query['select']['_file_platform_ids'] = group
        if data['text_query']:
            lang = get_language()
            joins = [
                'LEFT JOIN addons_users au on (au.addon_id = addons.id)',
                'LEFT JOIN users u on (u.id = au.user_id)',
                """LEFT JOIN translations AS supportemail_default ON
                        (supportemail_default.id = addons.supportemail AND
                         supportemail_default.locale=addons.defaultlocale)""",
                """LEFT JOIN translations AS supportemail_local ON
                        (supportemail_local.id = addons.supportemail AND
                         supportemail_local.locale=%%(%s)s)"""
                         % qs._param(lang),
                """LEFT JOIN translations AS ad_name_local ON
                        (ad_name_local.id = addons.name AND
                         ad_name_local.locale=%%(%s)s)"""
                         % qs._param(lang)]
            qs.base_query['from'].extend(joins)
            fuzzy_q = u'%' + data['text_query'] + u'%'
            qs = qs.filter_raw(
                    Q('addon_name LIKE', fuzzy_q) |
                    # Search translated add-on names / support emails in
                    # the editor's locale:
                    Q('ad_name_local.localized_string LIKE', fuzzy_q) |
                    Q('supportemail_default.localized_string LIKE', fuzzy_q) |
                    Q('supportemail_local.localized_string LIKE', fuzzy_q) |
                    Q('au.role IN', [amo.AUTHOR_ROLE_OWNER,
                                     amo.AUTHOR_ROLE_DEV],
                      'u.email LIKE', fuzzy_q))
        if data['waiting_time_days']:
            if data['waiting_time_days'] == '10+':
                # Special case
                args = ('waiting_time_days >=',
                        int(data['waiting_time_days'][:-1]))
            else:
                args = ('waiting_time_days <=', data['waiting_time_days'])
            if qs.sql_model.is_version_specific:
                qs = qs.having(*args)
            else:
                qs = qs.filter_raw(*args)
        return qs


class ReviewAddonForm(happyforms.Form):
    addon_files = forms.ModelMultipleChoiceField(required=False,
            queryset=File.objects.none(), label=_('Files:'),
            widget=forms.CheckboxSelectMultiple())
    comments = forms.CharField(required=True, widget=forms.Textarea(),
                               label=_('Comments:'))
    canned_response = forms.ChoiceField(required=False)
    action = forms.ChoiceField(required=True, widget=forms.RadioSelect())
    operating_systems = forms.CharField(required=False,
                                        label=_('Operating systems:'))
    applications = forms.CharField(required=False, label=_('Applications:'))
    notify = forms.BooleanField(required=False,
                                label=_('Notify me the next time this add-on '
                                        'is updated. (Subsequent updates will '
                                        'not generate an email)'))

    def is_valid(self):
        result = super(ReviewAddonForm, self).is_valid()
        if result:
            self.helper.set_data(self.cleaned_data)
        return result

    def __init__(self, *args, **kw):
        self.helper = kw.pop('helper')
        super(ReviewAddonForm, self).__init__(*args, **kw)
        self.fields['addon_files'].queryset = self.helper.all_files

        self.fields['canned_response'].choices = ([(c.response, c.name)
                                    for c in CannedResponse.objects.all()])
        self.fields['action'].choices = [(k, v['label']) for k, v
                                          in self.helper.actions.items()]


class ReviewFileForm(ReviewAddonForm):

    def clean_addon_files(self):
        files = self.data.getlist('addon_files')
        if self.data.get('action', '') == 'prelim':
            if not files:
                raise ValidationError(_('You must select some files.'))
            for pk in files:
                file = self.helper.all_files.get(pk=pk)
                if (file.status != amo.STATUS_UNREVIEWED and not
                    (self.helper.addon.status == amo.STATUS_LITE and
                     file.status == amo.STATUS_UNREVIEWED)):
                    raise ValidationError(_('File %s is not pending review.')
                                          % file.filename)
        return self.fields['addon_files'].queryset.filter(pk__in=files)


def get_review_form(data, request=None, addon=None, version=None):
    helper = ReviewHelper(request=request, addon=addon, version=version)

    form = {ReviewAddon: ReviewAddonForm,
            ReviewFiles: ReviewFileForm}[helper.handler.__class__]
    return form(data, helper=helper)


class MOTDForm(happyforms.Form):
    motd = forms.CharField(required=True, widget=widgets.Textarea())
