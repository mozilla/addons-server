from django import forms
from django.core.exceptions import ValidationError
from django.forms.fields import FileField


class BaseFormMixin(object):
    """
    We do some automatic stripping of globally bad input.  For example, we
    strip leading/trailing spaces from all data.

    This idea was wonfixed in django: http://code.djangoproject.com/ticket/6362
    """

    def _clean_fields(self):
        for name, field in self.fields.items():
            # value_from_datadict() gets the data from the data dictionaries.
            # Each widget type knows how to retrieve its own data, because some
            # widgets split data over several HTML fields.
            value = field.widget.value_from_datadict(self.data, self.files,
                                                     self.add_prefix(name))

            try:
                if isinstance(field, FileField):
                    initial = self.initial.get(name, field.initial)
                    value = field.clean(value, initial)
                else:
                    if isinstance(value, basestring):
                        value = field.clean(value.strip())
                    else:
                        value = field.clean(value)
                self.cleaned_data[name] = value
                if hasattr(self, 'clean_%s' % name):
                    value = getattr(self, 'clean_%s' % name)()
                    self.cleaned_data[name] = value
            except ValidationError as e:
                self._errors[name] = self.error_class(e.messages)
                if name in self.cleaned_data:
                    del self.cleaned_data[name]


class Form(BaseFormMixin, forms.Form):
    pass


class ModelForm(BaseFormMixin, forms.ModelForm):
    pass
