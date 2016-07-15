import datetime
import logging
from datetime import timedelta

from django import forms
from django.db.models import Q
from django.forms import widgets
from django.utils.translation import (
    ugettext as _, ugettext_lazy as _lazy, get_language)

from olympia import amo
from olympia.constants import editors as rvw
from olympia.addons.models import Addon, Persona
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import raise_required
from olympia.applications.models import AppVersion
from olympia.editors.models import CannedResponse, ReviewerScore, ThemeLock
from olympia.editors.tasks import approve_rereview, reject_rereview, send_mail
from olympia.lib import happyforms


log = logging.getLogger('z.reviewers.forms')


ACTION_FILTERS = (('', ''), ('approved', _lazy(u'Approved reviews')),
                  ('deleted', _lazy(u'Deleted reviews')))

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
        if 'end' in data and data['end']:
            data['end'] += timedelta(days=1)

        if 'filter' in data and data['filter']:
            data['filter'] = ACTION_DICT[data['filter']]
        return data


class BetaSignedLogForm(happyforms.Form):
    VALIDATION_CHOICES = (
        ('', ''),
        (amo.LOG.BETA_SIGNED_VALIDATION_PASSED.id,
         _lazy(u'Passed automatic validation')),
        (amo.LOG.BETA_SIGNED_VALIDATION_FAILED.id,
         _lazy(u'Failed automatic validation')))
    filter = forms.ChoiceField(required=False, choices=VALIDATION_CHOICES,
                               label=_lazy(u'Filter by automatic validation'))


class ReviewLogForm(happyforms.Form):
    start = forms.DateField(required=False,
                            label=_lazy(u'View entries between'))
    end = forms.DateField(required=False, label=_lazy(u'and'))
    search = forms.CharField(required=False, label=_lazy(u'containing'))

    def __init__(self, *args, **kw):
        super(ReviewLogForm, self).__init__(*args, **kw)

        # L10n: start, as in "start date"
        self.fields['start'].widget.attrs = {'placeholder': _('start'),
                                             'size': 10}

        # L10n: end, as in "end date"
        self.fields['end'].widget.attrs = {'size': 10, 'placeholder': _('end')}

        # L10n: Description of what can be searched for
        search_ph = _('add-on, editor or comment')
        self.fields['search'].widget.attrs = {'placeholder': search_ph,
                                              'size': 30}

    def clean(self):
        data = self.cleaned_data
        # We want this to be inclusive of the end date.
        if 'end' in data and data['end']:
            data['end'] += timedelta(days=1)

        return data


class QueueSearchForm(happyforms.Form):
    text_query = forms.CharField(
        required=False,
        label=_lazy(u'Search by add-on name / author email'))
    searching = forms.BooleanField(widget=forms.HiddenInput, required=False,
                                   initial=True)
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
        versions = AppVersion.objects.filter(application=app_id)
        return [('', '')] + [(v.version, v.version) for v in versions]

    def clean_addon_type_ids(self):
        if self.cleaned_data['addon_type_ids']:
            # Remove "Any Addon Extension" from the list so that no filter
            # is applied in that case.
            ids = set(self.cleaned_data['addon_type_ids'])
            self.cleaned_data['addon_type_ids'] = ids - set(str(amo.ADDON_ANY))
        return self.cleaned_data['addon_type_ids']

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
            qs = qs.filter_raw('apps_match.application_id =',
                               data['application_id'])
            # We join twice so it includes all apps, and not just the ones
            # filtered by the search criteria.
            app_join = ('LEFT JOIN applications_versions apps_match ON '
                        '(versions.id = apps_match.version_id)')
            qs.base_query['from'].extend([app_join])

            if data['max_version']:
                joins = ["""JOIN applications_versions vs
                            ON (versions.id = vs.version_id)""",
                         """JOIN appversions max_version
                            ON (max_version.id = vs.max)"""]
                qs.base_query['from'].extend(joins)
                qs = qs.filter_raw('max_version.version =',
                                   data['max_version'])
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
                         supportemail_local.locale=%%(%s)s)""" %
                qs._param(lang),
                """LEFT JOIN translations AS ad_name_local ON
                        (ad_name_local.id = addons.name AND
                         ad_name_local.locale=%%(%s)s)""" %
                qs._param(lang)]
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

            qs = qs.having(*args)
        return qs


class AllAddonSearchForm(happyforms.Form):
    text_query = forms.CharField(
        required=False,
        label=_lazy(u'Search by add-on name / author email / guid'))
    searching = forms.BooleanField(
        widget=forms.HiddenInput,
        required=False,
        initial=True)
    admin_review = forms.ChoiceField(
        required=False,
        choices=[('', ''), ('1', _lazy(u'yes')), ('0', _lazy(u'no'))],
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
    deleted = forms.ChoiceField(
        required=False,
        choices=[('', ''), ('1', _lazy(u'yes')), ('0', _lazy(u'no'))],
        label=_lazy(u'Deleted'))

    def __init__(self, *args, **kw):
        super(AllAddonSearchForm, self).__init__(*args, **kw)
        widget = self.fields['application_id'].widget
        # Get the URL after the urlconf has loaded.
        widget.attrs['data-url'] = reverse('editors.application_versions_json')

    def version_choices_for_app_id(self, app_id):
        versions = AppVersion.objects.filter(application=app_id)
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
                raise forms.ValidationError('No application selected')
        return self.cleaned_data['max_version']

    def filter_qs(self, qs):
        data = self.cleaned_data
        if data['admin_review']:
            qs = qs.filter(admin_review=data['admin_review'])
        if data['deleted']:
            qs = qs.filter(is_deleted=data['deleted'])
        if data['application_id']:
            qs = qs.filter_raw('apps_match.application_id =',
                               data['application_id'])
            # We join twice so it includes all apps, and not just the ones
            # filtered by the search criteria.
            app_join = ('LEFT JOIN applications_versions apps_match ON '
                        '(versions.id = apps_match.version_id)')
            qs.base_query['from'].extend([app_join])

            if data['max_version']:
                joins = ["""JOIN applications_versions vs
                            ON (versions.id = vs.version_id)""",
                         """JOIN appversions max_version
                            ON (max_version.id = vs.max)"""]
                qs.base_query['from'].extend(joins)
                qs = qs.filter_raw('max_version.version =',
                                   data['max_version'])
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
                         supportemail_local.locale=%%(%s)s)""" %
                qs._param(lang),
                """LEFT JOIN translations AS ad_name_local ON
                        (ad_name_local.id = addons.name AND
                         ad_name_local.locale=%%(%s)s)""" %
                qs._param(lang)]
            qs.base_query['from'].extend(joins)
            fuzzy_q = u'%' + data['text_query'] + u'%'
            qs = qs.filter_raw(
                Q('addon_name LIKE', fuzzy_q) |
                Q('guid LIKE', fuzzy_q) |
                # Search translated add-on names / support emails in
                # the editor's locale:
                Q('ad_name_local.localized_string LIKE', fuzzy_q) |
                Q('supportemail_default.localized_string LIKE', fuzzy_q) |
                Q('supportemail_local.localized_string LIKE', fuzzy_q) |
                Q('au.role IN', [amo.AUTHOR_ROLE_OWNER,
                                 amo.AUTHOR_ROLE_DEV],
                  'u.email LIKE', fuzzy_q))
        return qs


class NonValidatingChoiceField(forms.ChoiceField):
    """A ChoiceField that doesn't validate."""
    def validate(self, value):
        pass


class ReviewForm(happyforms.Form):
    comments = forms.CharField(required=True, widget=forms.Textarea(),
                               label=_lazy(u'Comments:'))
    canned_response = NonValidatingChoiceField(required=False)
    action = forms.ChoiceField(required=True, widget=forms.RadioSelect())
    operating_systems = forms.CharField(required=False,
                                        label=_lazy(u'Operating systems:'))
    applications = forms.CharField(required=False,
                                   label=_lazy(u'Applications:'))
    notify = forms.BooleanField(required=False,
                                label=_lazy(u'Notify me the next time this '
                                            'add-on is updated. (Subsequent '
                                            'updates will not generate an '
                                            'email)'))
    adminflag = forms.BooleanField(required=False,
                                   label=_lazy(u'Clear Admin Review Flag'))
    clear_info_request = forms.BooleanField(
        required=False, label=_lazy(u'Clear more info requested flag'))

    def is_valid(self):
        result = super(ReviewForm, self).is_valid()
        if result:
            self.helper.set_data(self.cleaned_data)
        return result

    def __init__(self, *args, **kw):
        self.helper = kw.pop('helper')
        self.type = kw.pop('type', amo.CANNED_RESPONSE_ADDON)
        super(ReviewForm, self).__init__(*args, **kw)

        # We're starting with an empty one, which will be hidden via CSS.
        canned_choices = [['', [('', _('Choose a canned response...'))]]]

        responses = CannedResponse.objects.filter(type=self.type)

        # Loop through the actions (prelim, public, etc).
        for k, action in self.helper.actions.iteritems():
            action_choices = [[c.response, c.name] for c in responses
                              if c.sort_group and k in c.sort_group.split(',')]

            # Add the group of responses to the canned_choices array.
            if action_choices:
                canned_choices.append([action['label'], action_choices])

        # Now, add everything not in a group.
        for r in responses:
            if not r.sort_group:
                canned_choices.append([r.response, r.name])

        self.fields['canned_response'].choices = canned_choices
        self.fields['action'].choices = [
            (k, v['label']) for k, v in self.helper.actions.items()]

    @property
    def unreviewed_files(self):
        return (self.helper.version.unreviewed_files
                if self.helper.version else [])


class MOTDForm(happyforms.Form):
    motd = forms.CharField(required=True, widget=widgets.Textarea())


class DeletedThemeLogForm(ReviewLogForm):

    def __init__(self, *args, **kwargs):
        super(DeletedThemeLogForm, self).__init__(*args, **kwargs)
        self.fields['search'].widget.attrs = {
            # L10n: Description of what can be searched for.
            'placeholder': _lazy(u'theme name'),
            'size': 30}


class ThemeReviewForm(happyforms.Form):
    theme = forms.ModelChoiceField(queryset=Persona.objects.all(),
                                   widget=forms.HiddenInput())
    action = forms.TypedChoiceField(
        choices=rvw.REVIEW_ACTIONS.items(),
        widget=forms.HiddenInput(attrs={'class': 'action'}),
        coerce=int, empty_value=None
    )
    # Duplicate is the same as rejecting but has its own flow.
    reject_reason = forms.TypedChoiceField(
        choices=rvw.THEME_REJECT_REASONS.items() + [('duplicate', '')],
        widget=forms.HiddenInput(attrs={'class': 'reject-reason'}),
        required=False, coerce=int, empty_value=None)
    comment = forms.CharField(
        required=False, widget=forms.HiddenInput(attrs={'class': 'comment'}))

    def clean_theme(self):
        theme = self.cleaned_data['theme']
        try:
            ThemeLock.objects.get(theme=theme)
        except ThemeLock.DoesNotExist:
            raise forms.ValidationError(
                _('Someone else is reviewing this theme.'))
        return theme

    def clean_reject_reason(self):
        reject_reason = self.cleaned_data.get('reject_reason', None)
        if (self.cleaned_data.get('action') == rvw.ACTION_REJECT and
                reject_reason is None):
            raise_required()
        return reject_reason

    def clean_comment(self):
        # Comment field needed for duplicate, flag, moreinfo, and other reject
        # reason.
        action = self.cleaned_data.get('action')
        reject_reason = self.cleaned_data.get('reject_reason')
        comment = self.cleaned_data.get('comment')
        if (not comment and (action == rvw.ACTION_FLAG or
                             action == rvw.ACTION_MOREINFO or
                             (action == rvw.ACTION_REJECT and
                              reject_reason == 0))):
            raise_required()
        return comment

    def save(self):
        action = self.cleaned_data['action']
        comment = self.cleaned_data.get('comment')
        reject_reason = self.cleaned_data.get('reject_reason')
        theme = self.cleaned_data['theme']

        is_rereview = (
            theme.rereviewqueuetheme_set.exists() and
            theme.addon.status not in (amo.STATUS_PENDING,
                                       amo.STATUS_REVIEW_PENDING))

        theme_lock = ThemeLock.objects.get(theme=self.cleaned_data['theme'])

        mail_and_log = True
        if action == rvw.ACTION_APPROVE:
            if is_rereview:
                approve_rereview(theme)
            theme.addon.update(status=amo.STATUS_PUBLIC)
            theme.approve = datetime.datetime.now()
            theme.save()

        elif action in (rvw.ACTION_REJECT, rvw.ACTION_DUPLICATE):
            if is_rereview:
                reject_rereview(theme)
            else:
                theme.addon.update(status=amo.STATUS_REJECTED)

        elif action == rvw.ACTION_FLAG:
            if is_rereview:
                mail_and_log = False
            else:
                theme.addon.update(status=amo.STATUS_REVIEW_PENDING)

        elif action == rvw.ACTION_MOREINFO:
            if not is_rereview:
                theme.addon.update(status=amo.STATUS_REVIEW_PENDING)

        if mail_and_log:
            send_mail(self.cleaned_data, theme_lock)

            # Log.
            amo.log(amo.LOG.THEME_REVIEW, theme.addon, details={
                    'theme': theme.addon.name.localized_string,
                    'action': action,
                    'reject_reason': reject_reason,
                    'comment': comment}, user=theme_lock.reviewer)
            log.info('%sTheme %s (%s) - %s' % (
                '[Rereview] ' if is_rereview else '', theme.addon.name,
                theme.id, action))

        score = 0
        if action in (rvw.ACTION_REJECT, rvw.ACTION_DUPLICATE,
                      rvw.ACTION_APPROVE):
            score = ReviewerScore.award_points(
                theme_lock.reviewer, theme.addon, theme.addon.status)
        theme_lock.delete()

        return score


class ThemeSearchForm(forms.Form):
    q = forms.CharField(
        required=False, label=_lazy(u'Search'),
        widget=forms.TextInput(attrs={'autocomplete': 'off',
                                      'placeholder': _lazy(u'Search')}))
    queue_type = forms.CharField(required=False, widget=forms.HiddenInput())


class ReviewThemeLogForm(ReviewLogForm):

    def __init__(self, *args, **kwargs):
        super(ReviewThemeLogForm, self).__init__(*args, **kwargs)
        self.fields['search'].widget.attrs = {
            # L10n: Description of what can be searched for.
            'placeholder': _lazy(u'theme, reviewer, or comment'),
            'size': 30}


class WhiteboardForm(forms.ModelForm):

    class Meta:
        model = Addon
        fields = ['whiteboard']
