from django import forms

import amo
from tower import ugettext as _


APP_UPSELL_CHOICES = (
    (0, _("I don't have a free app to associate.")),
    (1, _('This is a premium upgrade.')),
)


APP_PUBLIC_CHOICES = (
    (0, _('As soon as it is approved.')),
    (1, _('Not until I manually make it public.')),
)


class AddonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name
