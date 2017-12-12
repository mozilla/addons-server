from copy import copy

from django import forms
from django.conf import settings

from olympia.amo.fields import ReCaptchaField
from olympia.translations.fields import TranslatedField


class AbuseForm(forms.Form):
    recaptcha = ReCaptchaField(label='')
    text = forms.CharField(required=True,
                           label='',
                           widget=forms.Textarea())

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        self.has_recaptcha = True

        super(AbuseForm, self).__init__(*args, **kwargs)

        if (not self.request.user.is_anonymous() or
                not settings.NOBOT_RECAPTCHA_PRIVATE_KEY):
            del self.fields['recaptcha']
            self.has_recaptcha = False


class AMOModelForm(forms.ModelForm):

    def _get_changed_data(self):
        """
        The standard modelform thinks the Translation PKs are the initial
        values.  We need to dig deeper to assert whether there are indeed
        changes.
        """
        Model = self._meta.model
        if self._changed_data is None:
            changed = copy(forms.ModelForm.changed_data.__get__(self))
            fieldnames = [f.name for f in Model._meta.fields]
            fields = [(name, Model._meta.get_field(name))
                      for name in changed if name in fieldnames]
            trans = [name for name, field in fields
                     if isinstance(field, TranslatedField)]
            # If there are translated fields, pull the model from the database
            # and do comparisons.
            if trans:
                try:
                    orig = Model.objects.get(pk=self.instance.pk)
                except Model.DoesNotExist:
                    return self._changed_data

                for field in trans:
                    if getattr(orig, field) == getattr(self.instance, field):
                        self._changed_data.remove(field)

        return self._changed_data
    changed_data = property(_get_changed_data)
