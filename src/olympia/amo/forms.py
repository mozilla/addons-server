import itertools

from django import forms
from django.utils.functional import cached_property

from olympia.amo.utils import BaseModelSerializerAndFormMixin
from olympia.translations.fields import TranslatedField


class AMOModelForm(BaseModelSerializerAndFormMixin, forms.ModelForm):
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
            field.name
            for field in Model._meta.get_fields()
            if isinstance(field, TranslatedField) and field.name in changed_data
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


class LimitedModelChoiceField(forms.ModelChoiceField):
    limit_choice_count = 100  # django docs suggest 100 is the max you should use

    def __init__(self, queryset, *, limit_choice_count=None, **kwargs):
        if limit_choice_count is not None:
            self.limit_choice_count = limit_choice_count
        self.to_field_name = kwargs.get('to_field_name', None)
        super().__init__(queryset, **kwargs)

    def _set_queryset(self, queryset):
        if hasattr(self, '_choices'):
            del self._choices
        super()._set_queryset(queryset)

    queryset = property(forms.ModelChoiceField.queryset.fget, _set_queryset)

    def _get_choices(self):
        # If self._choices is set, we called this before.
        if hasattr(self, '_choices'):
            return self._choices

        count = self.limit_choice_count + (1 if self.empty_label else 0)
        # We need to limit the choices, but we can't slice the queryset.
        self._choices = list(itertools.islice(self.iterator(self), count))
        return self._choices

    choices = property(_get_choices, forms.ModelChoiceField.choices.fset)
