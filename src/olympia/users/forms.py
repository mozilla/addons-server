import os

from django import forms
from django.utils.translation import ugettext_lazy as _


class DeniedNameAddForm(forms.Form):
    """Form for adding denied names in bulk fashion."""
    names = forms.CharField(widget=forms.Textarea(
        attrs={'cols': 40, 'rows': 16}))

    def clean_names(self):
        names = os.linesep.join([
            s.strip() for s in self.cleaned_data['names'].splitlines()
            if s.strip()
        ])
        return names


class IPNetworkUserRestrictionForm(forms.ModelForm):
    ip_address = forms.GenericIPAddressField(
        required=False,
        label=_('IP Address'),
        help_text=_(
            'Enter a valid IPv4 or IPv6 address, e.g 127.0.0.1.'
            ' Will be converted into a /32 network.'))

    def clean(self):
        data = self.cleaned_data
        network, ip_address = data.get('network'), data.get('ip_address')

        if ip_address and network:
            raise forms.ValidationError(_(
                'You can only enter one, either IP Address or Network.'))
        elif ip_address is not None and not network:
            data['network'] = f'{ip_address}/32'

        return data
