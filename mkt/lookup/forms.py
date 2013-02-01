from django import forms

import happyforms
from tower import ugettext_lazy as _lazy


class TransactionSearchForm(happyforms.Form):
    q = forms.IntegerField(label=_lazy(u'Transaction Lookup'))

    label_suffix = ''


class TransactionRefundForm(happyforms.Form):
    refund_reason = forms.CharField(
        label=_lazy(u'Enter refund details to refund transaction'),
        widget=forms.Textarea(attrs={'rows': 4}))
