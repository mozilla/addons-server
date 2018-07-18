from django import forms
from django.utils.translation import ugettext_lazy as _

from olympia import amo
from olympia.compat import FIREFOX_COMPAT


APPVER_CHOICES = [
    (info['main'], '%s %s' % (unicode(amo.FIREFOX.pretty), info['main']))
    for info in FIREFOX_COMPAT
]


class AppVerForm(forms.Form):
    appver = forms.ChoiceField(
        choices=[('', _('All'))] + APPVER_CHOICES, required=False
    )
