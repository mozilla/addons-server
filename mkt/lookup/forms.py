from django import forms
from django.conf import settings

import happyforms
from tower import ugettext_lazy as _lazy


class TransactionSearchForm(happyforms.Form):
    q = forms.CharField(label=_lazy(u'Transaction Lookup'))
    label_suffix = ''


class TransactionRefundForm(happyforms.Form):
    # A manual refund is one that does not use the payment providers API
    # but has been processed manually.
    manual = forms.BooleanField(
        label=_lazy(u'Process a manual refund'),
        required=False)
    refund_reason = forms.CharField(
        label=_lazy(u'Enter refund details to refund transaction'),
        widget=forms.Textarea(attrs={'rows': 4}))
    fake = forms.ChoiceField(
        choices=(('OK', 'OK'), ('PENDING', 'Pending'), ('INVALID', 'Invalid')))

    def __init__(self, *args, **kw):
        super(TransactionRefundForm, self).__init__(*args, **kw)
        if not settings.BANGO_FAKE_REFUNDS:
            del self.fields['fake']


class DeleteUserForm(happyforms.Form):
    delete_reason = forms.CharField(
        label=_lazy(u'Reason for Deletion'),
        widget=forms.Textarea(attrs={'rows': 2}))
