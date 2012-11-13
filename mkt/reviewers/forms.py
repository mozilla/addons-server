from django import forms

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo.utils import raise_required
from addons.models import AddonDeviceType, Persona
from editors.forms import NonValidatingChoiceField, ReviewLogForm
from editors.models import CannedResponse
from mkt.reviewers.utils import ReviewHelper
import mkt.constants.reviewers as rvw
from .models import ThemeLock
from .tasks import send_mail


class ReviewAppForm(happyforms.Form):

    comments = forms.CharField(required=True, widget=forms.Textarea(),
                               label=_lazy(u'Comments:'))
    canned_response = NonValidatingChoiceField(required=False)
    action = forms.ChoiceField(required=True, widget=forms.RadioSelect())
    device_types = forms.CharField(required=False,
                                   label=_lazy(u'Device Types:'))
    browsers = forms.CharField(required=False,
                               label=_lazy(u'Browsers:'))
    device_override = forms.TypedMultipleChoiceField(
        choices=[(k, v.name) for k, v in amo.DEVICE_TYPES.items()],
        coerce=int, label=_lazy(u'Device Type Override:'),
        widget=forms.CheckboxSelectMultiple, required=False)
    notify = forms.BooleanField(
        required=False, label=_lazy(u'Notify me the next time the manifest is'
                                    u'updated. (Subsequent updates will not '
                                    u'generate an email)'))

    def __init__(self, *args, **kw):
        self.helper = kw.pop('helper')
        self.type = kw.pop('type', amo.CANNED_RESPONSE_APP)
        super(ReviewAppForm, self).__init__(*args, **kw)

        # We're starting with an empty one, which will be hidden via CSS.
        canned_choices = [['', [('', _('Choose a canned response...'))]]]

        responses = CannedResponse.objects.filter(type=self.type)

        # Loop through the actions.
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
        self.fields['action'].choices = [(k, v['label']) for k, v
                                         in self.helper.actions.items()]
        device_types = AddonDeviceType.objects.filter(
            addon=self.helper.addon).values_list('device_type', flat=True)
        if device_types:
            self.initial['device_override'] = device_types

    def is_valid(self):
        result = super(ReviewAppForm, self).is_valid()
        if result:
            self.helper.set_data(self.cleaned_data)
        return result


def get_review_form(data, request=None, addon=None, version=None):
    helper = ReviewHelper(request=request, addon=addon, version=version)
    return ReviewAppForm(data, helper=helper)


class ReviewAppLogForm(ReviewLogForm):

    def __init__(self, *args, **kwargs):
        super(ReviewAppLogForm, self).__init__(*args, **kwargs)
        self.fields['search'].widget.attrs = {
            # L10n: Descript of what can be searched for.
            'placeholder': _lazy(u'app, reviewer, or comment'),
            'size': 30}


class AppQueueSearchForm(happyforms.Form):
    text_query = forms.CharField(required=False,
                                 label=_lazy(u'Search by app name or author'
                                             ' email'))
    admin_review = forms.BooleanField(required=False,
                                      label=_lazy(u'Admin Flag'))
    has_editor_comment = forms.BooleanField(required=False,
                                            label=_lazy(u'Has Editor Comment'))
    has_info_request = forms.BooleanField(required=False,
        label=_lazy(u'Information Requested'))
    waiting_time_days = forms.TypedChoiceField(required=False, coerce=int,
        label=_lazy(u'Days Since Submission'),
        choices=([('', '')] + [(i, i) for i in range(1, 10)] + [(10, '10+')]))
    device_type_ids = forms.MultipleChoiceField(required=False,
            widget=forms.CheckboxSelectMultiple,
            label=_lazy(u'Device Type'),
            choices=[(d.id, d.name) for d in amo.DEVICE_TYPES.values()])

    # Changes wording from "I'll use my own system..." to fit context of queue.
    premium_types = dict(amo.ADDON_PREMIUM_TYPES)
    premium_types[amo.ADDON_OTHER_INAPP] = _(u'Other system')
    premium_type_ids = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        required=False, label=_lazy(u'Premium Type'),
        choices=premium_types.items())


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
    comment = forms.CharField(required=False,
        widget=forms.HiddenInput(attrs={'class': 'comment'}))

    def clean_theme(self):
        theme = self.cleaned_data['theme']
        try:
            ThemeLock.objects.get(theme=theme)
        except (ThemeLock.DoesNotExist):
            raise forms.ValidationError(
                _('Someone else is reviewing this theme.'))
        return theme

    def clean_reject_reason(self):
        reject_reason = self.cleaned_data.get('reject_reason', None)
        if (self.cleaned_data.get('action') == rvw.ACTION_REJECT
            and reject_reason is None):
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
        theme_lock = ThemeLock.objects.get(theme=self.cleaned_data['theme'])
        send_mail(self.cleaned_data, theme_lock)
        theme_lock.delete()
