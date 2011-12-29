from django import forms
from django.conf import settings
from django.forms.widgets import RadioSelect

from tower import ugettext_lazy as _

import amo


class CompatForm(forms.Form):
    appvers = [(amo.APP_IDS[d['app']], d['main']) for d in settings.COMPAT]
    _choices = [('%s-%s' % (app.id, ver), '%s %s' % (unicode(app.pretty), ver))
                for app, ver in appvers]
    appver = forms.ChoiceField(choices=_choices, required=False)
    type = forms.ChoiceField(choices=(('all', _('All Add-ons')),
                                      ('binary', _('Binary')),
                                      ('non-binary', _('Non-binary'))),
                             widget=RadioSelect, required=False)


class AdminCompatForm(CompatForm):
    _choices = [('%.1f' % (x / 10.0), '%.0f%%' % (x * 10))
                for x in xrange(9, -1, -1)]
    ratio = forms.ChoiceField(choices=_choices, required=False)
