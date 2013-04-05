from urlparse import urlparse

from django import forms

from tower import ugettext_lazy as _lazy

import amo
from addons.models import Addon


class ReceiptForm(forms.Form):
    app = forms.ModelChoiceField(queryset=
        Addon.objects.filter(type=amo.ADDON_WEBAPP))


class TestInstall(forms.Form):
    TYPE_CHOICES = (('none', _lazy('No receipt')),
                    ('ok', _lazy(u'Test receipt')),
                    ('expired', _lazy(u'Expired test receipt')),
                    ('invalid', _lazy(u'Invalid test receipt')),
                    ('refunded', _lazy(u'Refunded test receipt')))

    receipt_type = forms.ChoiceField(choices=TYPE_CHOICES)
    manifest_url = forms.URLField()

    @property
    def root(self):
        parsed = urlparse(self.cleaned_data['manifest_url'])
        return '%s://%s' % (parsed.scheme, parsed.netloc)
