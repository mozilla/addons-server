from django import forms

from tower import ugettext as _


APP_UPSELL_CHOICES = (
    (0, _("I don't have a free app to associate.")),
    (1, _('This is a premium upgrade.')),
)


class AddonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name

