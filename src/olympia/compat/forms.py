from django import forms
from django.forms.widgets import RadioSelect

from tower import ugettext_lazy as _

import amo


appvers = [(amo.APP_IDS[d['app']], d['main']) for d in amo.COMPAT]
APPVER_CHOICES = [
    ('%s-%s' % (app.id, ver), '%s %s' % (unicode(app.pretty), ver))
    for app, ver in appvers
]


class AppVerForm(forms.Form):
    appver = forms.ChoiceField(choices=[('', _('All'))] + APPVER_CHOICES,
                               required=False)


class CompatForm(forms.Form):
    appver = forms.ChoiceField(choices=APPVER_CHOICES, required=False)
    type = forms.ChoiceField(choices=(('all', _('All Add-ons')),
                                      ('binary', _('Binary')),
                                      ('non-binary', _('Non-binary'))),
                             widget=RadioSelect, required=False)
