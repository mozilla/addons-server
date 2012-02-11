from django import forms
from django.utils.safestring import mark_safe

import happyforms
from tower import ugettext_lazy as _lazy

from users.models import UserProfile


class DevAgreementForm(happyforms.ModelForm):
    read_dev_agreement = forms.BooleanField(
        label=mark_safe(_lazy('<b>Agree</b> and Continue')),
        widget=forms.HiddenInput)

    class Meta:
        model = UserProfile
        fields = ('read_dev_agreement',)
