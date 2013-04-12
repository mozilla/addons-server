from django import forms
from django.conf import settings

import happyforms
from tower import ugettext_lazy as _lazy


class TransactionSearchForm(happyforms.Form):
    q = forms.CharField(label=_lazy(u'Transaction Lookup'))
    label_suffix = ''


class TransactionRefundForm(happyforms.Form):
    refund_reason = forms.CharField(
        label=_lazy(u'Enter refund details to refund transaction'),
        widget=forms.Textarea(attrs={'rows': 4}))
    fake = forms.ChoiceField(
        choices=(('OK', 'OK'), ('PENDING', 'Pending'), ('INVALID', 'Invalid')))

    def __init__(self, *args, **kw):
        super(TransactionRefundForm, self).__init__(*args, **kw)
        if not settings.BANGO_FAKE_REFUNDS:
            del self.fields['fake']
