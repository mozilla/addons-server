from django import forms

import happyforms


class PriceCurrencyForm(happyforms.Form):
    currency = forms.ChoiceField(choices=(), required=False)

    def __init__(self, price=None, *args, **kw):
        self.price = price
        super(PriceCurrencyForm, self).__init__(*args, **kw)
        self.fields['currency'].choices = self.price.currencies()

    def get_tier(self):
        for k, v in self.fields['currency'].choices:
            if k == self.cleaned_data['currency']:
                return v
