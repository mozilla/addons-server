from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

from olympia.api.throttling import (
    CheckThrottlesFormMixin,
    GranularIPRateThrottle,
    GranularUserRateThrottle,
)


class AbuseAppealEmailIPThrottle(GranularIPRateThrottle):
    rate = '20/day'
    scope = 'ip_abuse_appeal_email'


class AbuseAppealUserThrottle(GranularUserRateThrottle):
    rate = '20/day'
    scope = 'user_abuse_appeal'


class AbuseAppealIPThrottle(GranularIPRateThrottle):
    rate = '20/day'
    scope = 'ip_abuse_appeal'


class AbuseAppealEmailForm(CheckThrottlesFormMixin, forms.Form):
    # Note: the label is generic on purpose. It could be an appeal from the
    # reporter, or from the target of a ban (who can no longer log in).
    email = forms.EmailField(label=_('Email address'))

    throttle_classes = (AbuseAppealEmailIPThrottle,)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        self.expected_email = kwargs.pop('expected_email')
        if not self.expected_email:
            raise ImproperlyConfigured(
                'AbuseAppealEmailForm called without an expected_email'
            )
        return super().__init__(*args, **kwargs)

    def clean_email(self):
        if (email := self.cleaned_data['email']) != self.expected_email:
            raise forms.ValidationError(_('Invalid email provided.'))
        return email


class AbuseAppealForm(CheckThrottlesFormMixin, forms.Form):
    throttle_classes = (
        AbuseAppealIPThrottle,
        AbuseAppealUserThrottle,
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        return super().__init__(*args, **kwargs)

    reason = forms.CharField(
        widget=forms.Textarea(),
        label=_('Reason for appeal'),
        help_text=_(
            'Please explain why you believe that this decision was made in error, '
            'and/or does not align with the applicable policy or law.'
        ),
    )
