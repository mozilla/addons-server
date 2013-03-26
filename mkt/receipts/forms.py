from django import forms

import amo
from addons.models import Addon


class ReceiptForm(forms.Form):
    app = forms.ModelChoiceField(queryset=
        Addon.objects.filter(type=amo.ADDON_WEBAPP))
