from django import forms
from django.conf import settings

from olympia.amo.fields import ReCaptchaField
from olympia.translations.fields import TranslatedField
from django.utils.functional import cached_property


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

    @cached_property
    def changed_data(self):
        """
        The standard modelform thinks the Translation PKs are the initial
        values. We need to dig deeper to assert whether there are indeed
        changes.
        """
        Model = self._meta.model

        # Get a copy of the data since we'll be modifying it
        changed_data = forms.ModelForm.changed_data.__get__(self)[:]

        changed_translation_fields = [
            field.name for field in Model._meta.get_fields()
            if isinstance(field, TranslatedField) and
            field.name in changed_data
        ]

        # If there are translated fields, pull the model from the database
        # and do comparisons.
        if changed_translation_fields:
            try:
                orig = Model.objects.get(pk=self.instance.pk)
            except Model.DoesNotExist:
                return changed_data

            for field in changed_translation_fields:
                if getattr(orig, field) == getattr(self.instance, field):
                    changed_data.remove(field)

        return changed_data
