import os

from django import forms

from olympia.amo.forms import AMOModelForm


class DeniedNameAddForm(forms.Form):
    """Form for adding denied names in bulk fashion."""

    names = forms.CharField(widget=forms.Textarea(attrs={'cols': 40, 'rows': 16}))

    def clean_names(self):
        names = os.linesep.join(
            [s.strip() for s in self.cleaned_data['names'].splitlines() if s.strip()]
        )
        return names


class EmailUserRestrictionAdminForm(AMOModelForm):
    class Meta:
        help_texts = {
            'email_pattern': (
                'Enter full email that should be blocked or use unix-style wildcards, '
                'e.g. "*@example.com". If you need to block a domain incl subdomains, '
                'add a second entry, e.g. "*@*.example.com". Note that normalization '
                'is automatically applied at all times, e.g. foo+bar@example.com will '
                'be recorded as foo@example.com and match all variations.'
            ),
        }

    def clean_email_pattern(self):
        # Normalize email pattern when cleaning - we're also automatically
        # doing that in the save() method, but we want uniqueness check to
        # consider the normalized version and raise an error to the user if
        # they entered a pattern that already exists in its normalized form
        # in the database.
        email_pattern = self.cleaned_data['email_pattern']
        return self._meta.model.normalize_email(email_pattern)


class IPNetworkUserRestrictionForm(AMOModelForm):
    ip_address = forms.GenericIPAddressField(
        required=False,
        label='IP Address',
        help_text=(
            'Enter a valid IPv4 or IPv6 address, e.g 127.0.0.1.'
            ' Will be converted into a /32 network.'
        ),
    )

    def clean(self):
        data = self.cleaned_data
        network, ip_address = data.get('network'), data.get('ip_address')

        if ip_address and network:
            raise forms.ValidationError(
                'You can only enter one, either IP Address or Network.'
            )
        elif ip_address is not None and not network:
            data['network'] = f'{ip_address}/32'

        return data
