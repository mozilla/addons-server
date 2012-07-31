from django import forms

from tower import ugettext as _


APP_PUBLIC_CHOICES = (
    (0, _('As soon as it is approved.')),
    (1, _('Not until I manually make it public.')),
)


class AddonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name
