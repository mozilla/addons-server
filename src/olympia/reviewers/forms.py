# -*- coding: utf-8 -*-
from datetime import timedelta

from django import forms
from django.db.models import Q
from django.forms import widgets
from django.forms.models import (
    BaseModelFormSet,
    ModelMultipleChoiceField,
    modelformset_factory,
)
from django.urls import reverse
from django.utils.translation import get_language, gettext, gettext_lazy as _

import olympia.core.logger

from olympia import amo, ratings
from olympia.access import acl
from olympia.applications.models import AppVersion
from olympia.constants.reviewers import REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT
from olympia.ratings.models import Rating
from olympia.ratings.permissions import user_can_delete_rating
from olympia.reviewers.models import CannedResponse, Whiteboard
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.reviewers.forms')


ACTION_FILTERS = (
    ('', ''),
    ('approved', _('Approved reviews')),
    ('deleted', _('Deleted reviews')),
)

ACTION_DICT = dict(approved=amo.LOG.APPROVE_RATING, deleted=amo.LOG.DELETE_RATING)


class RatingModerationLogForm(forms.Form):
    start = forms.DateField(required=False, label=_('View entries between'))
    end = forms.DateField(required=False, label=_('and'))
    filter = forms.ChoiceField(
        required=False, choices=ACTION_FILTERS, label=_('Filter by type/action')
    )

    def clean(self):
        data = self.cleaned_data
        # We want this to be inclusive of the end date.
        if 'end' in data and data['end']:
            data['end'] += timedelta(days=1)

        if 'filter' in data and data['filter']:
            data['filter'] = ACTION_DICT[data['filter']]
        return data


class ReviewLogForm(forms.Form):
    start = forms.DateField(required=False, label=_('View entries between'))
    end = forms.DateField(required=False, label=_('and'))
    search = forms.CharField(required=False, label=_('containing'))

    def __init__(self, *args, **kw):
        super(ReviewLogForm, self).__init__(*args, **kw)

        # L10n: start, as in "start date"
        self.fields['start'].widget.attrs = {
            'placeholder': gettext('start'),
            'size': 10,
        }

        # L10n: end, as in "end date"
        self.fields['end'].widget.attrs = {'size': 10, 'placeholder': gettext('end')}

        # L10n: Description of what can be searched for
        search_ph = gettext('add-on, reviewer or comment')
        self.fields['search'].widget.attrs = {'placeholder': search_ph, 'size': 30}

    def clean(self):
        data = self.cleaned_data
        # We want this to be inclusive of the end date.
        if 'end' in data and data['end']:
            data['end'] += timedelta(days=1)

        return data


class QueueSearchForm(forms.Form):
    text_query = forms.CharField(
        required=False, label=_('Search by add-on name / author email')
    )
    searching = forms.BooleanField(
        widget=forms.HiddenInput, required=False, initial=True
    )
    needs_admin_code_review = forms.ChoiceField(
        required=False,
        label=_('Needs Admin Code Review'),
        choices=[('', ''), ('1', _('yes')), ('0', _('no'))],
    )
    application_id = forms.ChoiceField(
        required=False,
        label=_('Application'),
        choices=([('', '')] + [(a.id, a.pretty) for a in amo.APPS_ALL.values()]),
    )
    addon_type_ids = forms.MultipleChoiceField(
        required=False,
        label=_('Add-on Types'),
        choices=[(amo.ADDON_ANY, _('Any'))] + list(amo.ADDON_TYPES.items()),
    )

    def __init__(self, *args, **kw):
        super(QueueSearchForm, self).__init__(*args, **kw)

    def clean_addon_type_ids(self):
        if self.cleaned_data['addon_type_ids']:
            # Remove "Any Addon Extension" from the list so that no filter
            # is applied in that case.
            ids = set(self.cleaned_data['addon_type_ids'])
            self.cleaned_data['addon_type_ids'] = ids - set(str(amo.ADDON_ANY))
        return self.cleaned_data['addon_type_ids']

    def filter_qs(self, qs):
        data = self.cleaned_data
        if data['needs_admin_code_review']:
            qs = qs.filter(needs_admin_code_review=data['needs_admin_code_review'])
        if data['addon_type_ids']:
            qs = qs.filter_raw('addon_type_id IN', data['addon_type_ids'])
        if data['application_id']:
            qs = qs.filter_raw('apps_match.application_id =', data['application_id'])
            # We join twice so it includes all apps, and not just the ones
            # filtered by the search criteria.
            app_join = (
                'LEFT JOIN applications_versions apps_match ON '
                '(versions.id = apps_match.version_id)'
            )
            qs.base_query['from'].extend([app_join])

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
                % qs._param(lang),
            ]
            qs.base_query['from'].extend(joins)
            fuzzy_q = '%' + data['text_query'] + '%'
            qs = qs.filter_raw(
                Q('addon_name LIKE', fuzzy_q)
                # Search translated add-on names / support emails in
                # the reviewer's locale:
                | Q('ad_name_local.localized_string LIKE', fuzzy_q)
                | Q('supportemail_default.localized_string LIKE', fuzzy_q)
                | Q('supportemail_local.localized_string LIKE', fuzzy_q)
                | Q(
                    'au.role IN',
                    [amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV],
                    'u.email LIKE',
                    fuzzy_q,
                )
            )
        return qs


class AllAddonSearchForm(forms.Form):
    text_query = forms.CharField(
        required=False, label=_('Search by add-on name / author email / guid')
    )
    searching = forms.BooleanField(
        widget=forms.HiddenInput, required=False, initial=True
    )
    needs_admin_code_review = forms.ChoiceField(
        required=False,
        label=_('Needs Admin Code Review'),
        choices=[('', ''), ('1', _('yes')), ('0', _('no'))],
    )
    application_id = forms.ChoiceField(
        required=False,
        label=_('Application'),
        choices=([('', '')] + [(a.id, a.pretty) for a in amo.APPS_ALL.values()]),
    )
    max_version = forms.ChoiceField(
        required=False,
        label=_('Max. Version'),
        choices=[('', _('Select an application first'))],
    )
    deleted = forms.ChoiceField(
        required=False,
        choices=[('', ''), ('1', _('yes')), ('0', _('no'))],
        label=_('Deleted'),
    )

    def __init__(self, *args, **kw):
        super(AllAddonSearchForm, self).__init__(*args, **kw)
        widget = self.fields['application_id'].widget
        # Get the URL after the urlconf has loaded.
        widget.attrs['data-url'] = reverse('reviewers.application_versions_json')

    def version_choices_for_app_id(self, app_id):
        versions = AppVersion.objects.filter(application=app_id)
        return [('', '')] + [(v.version, v.version) for v in versions]

    def clean_application_id(self):
        if self.cleaned_data['application_id']:
            choices = self.version_choices_for_app_id(
                self.cleaned_data['application_id']
            )
            self.fields['max_version'].choices = choices
        return self.cleaned_data['application_id']

    def clean_max_version(self):
        if self.cleaned_data['max_version']:
            if not self.cleaned_data['application_id']:
                raise forms.ValidationError('No application selected')
        return self.cleaned_data['max_version']

    def filter_qs(self, qs):
        data = self.cleaned_data
        if data['needs_admin_code_review']:
            qs = qs.filter(needs_admin_code_review=data['needs_admin_code_review'])
        if data['deleted']:
            qs = qs.filter(is_deleted=data['deleted'])
        if data['application_id']:
            qs = qs.filter_raw('apps_match.application_id =', data['application_id'])
            # We join twice so it includes all apps, and not just the ones
            # filtered by the search criteria.
            app_join = (
                'LEFT JOIN applications_versions apps_match ON '
                '(versions.id = apps_match.version_id)'
            )
            qs.base_query['from'].extend([app_join])

            if data['max_version']:
                joins = [
                    """JOIN applications_versions vs
                            ON (versions.id = vs.version_id)""",
                    """JOIN appversions max_version
                            ON (max_version.id = vs.max)""",
                ]
                qs.base_query['from'].extend(joins)
                qs = qs.filter_raw('max_version.version =', data['max_version'])
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
                % qs._param(lang),
            ]
            qs.base_query['from'].extend(joins)
            fuzzy_q = '%' + data['text_query'] + '%'
            qs = qs.filter_raw(
                Q('addon_name LIKE', fuzzy_q)
                | Q('guid LIKE', fuzzy_q)
                # Search translated add-on names / support emails in
                # the reviewer's locale:
                | Q('ad_name_local.localized_string LIKE', fuzzy_q)
                | Q('supportemail_default.localized_string LIKE', fuzzy_q)
                | Q('supportemail_local.localized_string LIKE', fuzzy_q)
                | Q(
                    'au.role IN',
                    [amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV],
                    'u.email LIKE',
                    fuzzy_q,
                )
            )
        return qs


class NonValidatingChoiceField(forms.ChoiceField):
    """A ChoiceField that doesn't validate."""

    def validate(self, value):
        pass


class NumberInput(widgets.Input):
    input_type = 'number'


class VersionsChoiceField(ModelMultipleChoiceField):
    """
    Widget to use together with VersionsChoiceWidget to display the list of
    versions used by review page for some actions.
    """

    def label_from_instance(self, obj):
        """Return the object instead of transforming into a label at this stage
        so that it's available in the widget."""
        return obj


class VersionsChoiceWidget(forms.SelectMultiple):
    """
    Widget to use together with VersionsChoiceField to display the list of
    versions used by review page for some actions.
    """

    actions_filters = {
        amo.STATUS_APPROVED: ('confirm_multiple_versions', 'block_multiple_versions'),
        amo.STATUS_AWAITING_REVIEW: ('reject_multiple_versions',),
    }

    def create_option(self, *args, **kwargs):
        option = super().create_option(*args, **kwargs)
        # label_from_instance() on VersionsChoiceField returns the full object,
        # not a label, this is what makes this work.
        obj = option['label']
        status = obj.current_file.status if obj.current_file else None
        versions_actions = getattr(self, 'versions_actions', None)
        if versions_actions and obj.channel == amo.RELEASE_CHANNEL_UNLISTED:
            # For unlisted, some actions should only apply to approved/pending
            # versions, so we add our special `data-toggle` class and the
            # right `data-value` depending on status.
            option['attrs']['class'] = 'data-toggle'
            option['attrs']['data-value'] = '|'.join(
                self.actions_filters.get(status, ()) + ('',)
            )
        # Just in case, let's now force the label to be a string (it would be
        # converted anyway, but it's probably safer that way).
        option['label'] = str(obj)
        return option


class ReviewForm(forms.Form):
    # Hack to restore behavior from pre Django 1.10 times.
    # Django 1.10 enabled `required` rendering for required widgets. That
    # wasn't the case before, this should be fixed properly but simplifies
    # the actual Django 1.11 deployment for now.
    # See https://github.com/mozilla/addons-server/issues/8912 for proper fix.
    use_required_attribute = False

    comments = forms.CharField(
        required=True, widget=forms.Textarea(), label=_('Comments:')
    )
    canned_response = NonValidatingChoiceField(required=False)
    action = forms.ChoiceField(required=True, widget=forms.RadioSelect())
    versions = VersionsChoiceField(
        # The <select> is displayed/hidden dynamically depending on the action
        # so it needs the data-toggle class (data-value attribute is set later
        # during __init__). VersionsChoiceWidget takes care of adding that to
        # the individual <option> which is also needed for unlisted review
        # where for some actions we display the dropdown hiding some of the
        # versions it contains.
        widget=VersionsChoiceWidget(attrs={'class': 'data-toggle'}),
        required=False,
        queryset=Version.objects.none(),
    )  # queryset is set later in __init__.

    operating_systems = forms.CharField(required=False, label=_('Operating systems:'))
    applications = forms.CharField(required=False, label=_('Applications:'))
    delayed_rejection = forms.BooleanField(
        # For the moment we default to immediate rejections, but in the future
        # this will have to be dynamically set in __init__() to default to
        # delayed for listed review, and immediate for unlisted (the default
        # matters especially for unlisted where we don't intend to even show
        # the inputs, so we'll always use the initial value).
        # See https://github.com/mozilla/addons-server/pull/15025
        initial=False,
        required=False,
        widget=forms.RadioSelect(
            choices=(
                (
                    True,
                    _(
                        'Delay rejection, requiring developer to correct in '
                        'less than…'
                    ),
                ),
                (
                    False,
                    _(
                        'Reject immediately. Only use in case of serious '
                        'security issues.'
                    ),
                ),
            )
        ),
    )
    delayed_rejection_days = forms.IntegerField(
        required=False,
        widget=NumberInput,
        initial=REVIEWER_DELAYED_REJECTION_PERIOD_DAYS_DEFAULT,
        label=_('days'),
        min_value=1,
        max_value=99,
    )

    def is_valid(self):
        # Some actions do not require comments.
        action = self.helper.actions.get(self.data.get('action'))
        if action:
            if not action.get('comments', True):
                self.fields['comments'].required = False
            if action.get('versions', False):
                self.fields['versions'].required = True
        result = super(ReviewForm, self).is_valid()
        if result:
            self.helper.set_data(self.cleaned_data)
        return result

    def __init__(self, *args, **kw):
        self.helper = kw.pop('helper')
        super(ReviewForm, self).__init__(*args, **kw)

        # Delayed rejection period needs to be readonly unless we're an admin.
        user = self.helper.handler.user
        rejection_period_widget_attributes = {}
        rejection_period = self.fields['delayed_rejection_days']
        if not acl.action_allowed_user(user, amo.permissions.REVIEWS_ADMIN):
            rejection_period.min_value = rejection_period.initial
            rejection_period.max_value = rejection_period.initial
            rejection_period_widget_attributes['readonly'] = 'readonly'
        rejection_period_widget_attributes['min'] = rejection_period.min_value
        rejection_period_widget_attributes['max'] = rejection_period.max_value
        rejection_period.widget.attrs.update(rejection_period_widget_attributes)

        # With the helper, we now have the add-on and can set queryset on the
        # versions field correctly. Small optimization: we only need to do this
        # if the relevant actions are available, otherwise we don't really care
        # about this field.
        versions_actions = [
            k for k in self.helper.actions if self.helper.actions[k].get('versions')
        ]
        if versions_actions:
            if self.helper.version:
                channel = self.helper.version.channel
            else:
                channel = amo.RELEASE_CHANNEL_LISTED
            statuses = (amo.STATUS_APPROVED, amo.STATUS_AWAITING_REVIEW)
            self.fields['versions'].widget.versions_actions = versions_actions
            self.fields['versions'].queryset = (
                self.helper.addon.versions(manager='unfiltered_for_relations')
                .filter(channel=channel, files__status__in=statuses)
                .no_transforms()
                .prefetch_related('files')
                .distinct()
                .order_by('created')
            )
            # Reset data-value depending on widget depending on actions
            # available ([''] added to get an extra '|' at the end).
            self.fields['versions'].widget.attrs['data-value'] = '|'.join(
                versions_actions + ['']
            )
        # For the canned responses, we're starting with an empty one, which
        # will be hidden via CSS.
        canned_choices = [['', [('', gettext('Choose a canned response...'))]]]

        canned_type = (
            amo.CANNED_RESPONSE_TYPE_THEME
            if self.helper.addon.type == amo.ADDON_STATICTHEME
            else amo.CANNED_RESPONSE_TYPE_ADDON
        )
        responses = CannedResponse.objects.filter(type=canned_type)

        # Loop through the actions (public, etc).
        for k, action in self.helper.actions.items():
            action_choices = [
                [c.response, c.name]
                for c in responses
                if c.sort_group and k in c.sort_group.split(',')
            ]

            # Add the group of responses to the canned_choices array.
            if action_choices:
                canned_choices.append([action['label'], action_choices])

        # Now, add everything not in a group.
        for canned_response in responses:
            if not canned_response.sort_group:
                canned_choices.append([canned_response.response, canned_response.name])
        self.fields['canned_response'].choices = canned_choices

        # Set choices on the action field dynamically to raise an error when
        # someone tries to use an action they don't have access to.
        self.fields['action'].choices = [
            (k, v['label']) for k, v in self.helper.actions.items()
        ]

    @property
    def unreviewed_files(self):
        return self.helper.version.unreviewed_files if self.helper.version else []


class MOTDForm(forms.Form):
    motd = forms.CharField(required=True, widget=widgets.Textarea())


class WhiteboardForm(forms.ModelForm):
    class Meta:
        model = Whiteboard
        fields = ['private', 'public']
        labels = {'private': _('Private Whiteboard'), 'public': _('Whiteboard')}


class PublicWhiteboardForm(forms.ModelForm):
    class Meta:
        model = Whiteboard
        fields = ['public']
        labels = {'public': _('Whiteboard')}


class ModerateRatingFlagForm(forms.ModelForm):

    action_choices = [
        (ratings.REVIEW_MODERATE_KEEP, _('Keep review; remove flags')),
        (ratings.REVIEW_MODERATE_SKIP, _('Skip for now')),
        (ratings.REVIEW_MODERATE_DELETE, _('Delete review')),
    ]
    action = forms.ChoiceField(
        choices=action_choices, required=False, initial=0, widget=forms.RadioSelect()
    )

    class Meta:
        model = Rating
        fields = ('action',)


class BaseRatingFlagFormSet(BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(BaseRatingFlagFormSet, self).__init__(*args, **kwargs)

    def save(self):
        for form in self.forms:
            if form.cleaned_data and user_can_delete_rating(
                self.request, form.instance
            ):
                action = int(form.cleaned_data['action'])

                if action == ratings.REVIEW_MODERATE_DELETE:
                    form.instance.delete(user_responsible=self.request.user)
                elif action == ratings.REVIEW_MODERATE_KEEP:
                    form.instance.approve(user=self.request.user)


RatingFlagFormSet = modelformset_factory(
    Rating, extra=0, form=ModerateRatingFlagForm, formset=BaseRatingFlagFormSet
)
