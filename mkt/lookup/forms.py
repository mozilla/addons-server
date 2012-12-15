from django import forms

import happyforms
from tower import ugettext_lazy as _lazy


class TransactionSearchForm(happyforms.Form):
    q = forms.IntegerField(label=_lazy(u'Transaction Lookup'))

    label_suffix = ''
