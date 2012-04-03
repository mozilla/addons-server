from django import forms

import happyforms


class PriceCurrencyForm(happyforms.Form):
    currency = forms.ChoiceField(choices=(), required=False)

    def __init__(self, addon=None, *args, **kw):
        super(PriceCurrencyForm, self).__init__(*args, **kw)
        self.fields['currency'].choices = addon.premium.supported_currencies()

    def get_tier(self):
        for k, v in self.fields['currency'].choices:
            if k == self.cleaned_data['currency']:
                return v
