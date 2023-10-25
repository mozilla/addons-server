from django import forms
from django.utils.translation import gettext_lazy as _


class AbuseAppealEmailForm(forms.Form):
    # Note: the label is generic on purpose. It could be an appeal from the
    # reporter, or from the target of a ban (who can no longer log in).
    email = forms.EmailField(label=_('Email address'))

    def __init__(self, *args, **kwargs):
        self.expected_email = kwargs.pop('expected_email')
        return super().__init__(*args, **kwargs)

    def clean_email(self):
        if (email := self.cleaned_data['email']) != self.expected_email:
            raise forms.ValidationError(_('Invalid email provided.'))
        return email


class AbuseAppealForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea())
