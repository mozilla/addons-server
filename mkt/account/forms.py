import re

from django import forms
from django.conf import settings

import captcha.fields
import commonware.log
import happyforms
from tower import ugettext_lazy as _lazy

import amo
from market.models import PriceCurrency
from users.forms import BaseAdminUserEditForm
from users.models import UserProfile

log = commonware.log.getLogger('z.users')
admin_re = re.compile('(?=.*\d)(?=.*[a-zA-Z])')


class UserEditForm(happyforms.ModelForm):
    display_name = forms.CharField(label=_lazy(u'Display Name'), max_length=50,
        required=False,
        help_text=_lazy(u'This will be publicly displayed next to your '
                         'ratings, collections, and other contributions.'))

    class Meta:
        model = UserProfile
        fields = 'display_name',


class AdminUserEditForm(BaseAdminUserEditForm, UserEditForm):
    """
    This extends from the old `AdminUserEditForm` but using our new fancy
    `UserEditForm`.
    """
    admin_log = forms.CharField(required=True, label='Reason for change',
                                widget=forms.Textarea(attrs={'rows': 4}))
    notes = forms.CharField(required=False, label='Notes',
                            widget=forms.Textarea(attrs={'rows': 4}))
    anonymize = forms.BooleanField(required=False)
    restricted = forms.BooleanField(required=False)

    def save(self, *args, **kw):
        profile = super(AdminUserEditForm, self).save()
        if self.cleaned_data['anonymize']:
            amo.log(amo.LOG.ADMIN_USER_ANONYMIZED, self.instance,
                    self.cleaned_data['admin_log'])
            profile.anonymize()  # This also logs.
        else:
            if ('restricted' in self.changed_data and
                self.cleaned_data['restricted']):
                amo.log(amo.LOG.ADMIN_USER_RESTRICTED, self.instance,
                        self.cleaned_data['admin_log'])
                profile.restrict()
            else:
                amo.log(amo.LOG.ADMIN_USER_EDITED, self.instance,
                        self.cleaned_data['admin_log'], details=self.changes())
                log.info('Admin edit user: %s changed fields: %s' %
                         (self.instance, self.changed_fields()))
        return profile


class UserDeleteForm(forms.Form):
    confirm = forms.BooleanField(
        label=_lazy(u'I understand this step cannot be undone.'))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UserDeleteForm, self).__init__(*args, **kwargs)

    def clean(self):
        amouser = self.request.user.get_profile()
        if amouser.is_developer:
            # This is tampering because the form isn't shown on the page if
            # the user is a developer.
            log.warning(u'[Tampering] Attempt to delete developer account (%s)'
                                                          % self.request.user)
            raise forms.ValidationError('Developers cannot delete their '
                                        'accounts.')


class CurrencyForm(happyforms.Form):
    currency = forms.ChoiceField(widget=forms.RadioSelect)

    def __init__(self, *args, **kw):
        super(CurrencyForm, self).__init__(*args, **kw)
        choices = [u'USD'] + list((PriceCurrency.objects
                                        .values_list('currency', flat=True)
                                        .distinct()))
        self.fields['currency'].choices = [(k, amo.PAYPAL_CURRENCIES[k])
                                              for k in choices if k]


class FeedbackForm(happyforms.Form):
    """Site feedback form."""
    feedback = forms.CharField(required=True, widget=forms.Textarea, label='')
    platform = forms.CharField(required=False, widget=forms.HiddenInput,
                               label='')
    chromeless = forms.CharField(required=False, widget=forms.HiddenInput,
                                 label='')

    recaptcha = captcha.fields.ReCaptchaField(label='')

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        self.has_recaptcha = True

        super(FeedbackForm, self).__init__(*args, **kwargs)

        if (not self.request.user.is_anonymous() or
            not settings.RECAPTCHA_PRIVATE_KEY):
            del self.fields['recaptcha']
            self.has_recaptcha = False
