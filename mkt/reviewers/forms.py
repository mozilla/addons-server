from django import forms

import happyforms
from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo.utils import raise_required
from addons.models import Persona
from editors.forms import ReviewAddonForm, ReviewLogForm
from mkt.reviewers.utils import ReviewHelper
import mkt.constants.reviewers as rvw
from .models import ThemeLock
from .tasks import send_mail


class ReviewAppForm(ReviewAddonForm):

    def __init__(self, *args, **kw):
        kw.update(type=amo.CANNED_RESPONSE_APP)
        super(ReviewAppForm, self).__init__(*args, **kw)
        # We don't want to disable any app files:
        self.addon_files_disabled = tuple([])
        self.fields['notify'].label = _lazy(
            u'Notify me the next time the manifest is updated. (Subsequent '
             'updates will not generate an email.)')


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
            and reject_reason == None):
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
