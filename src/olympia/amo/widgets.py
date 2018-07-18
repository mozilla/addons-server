from django.forms.widgets import Input


class EmailWidget(Input):
    """HTML5 email type."""

    input_type = 'email'

    def __init__(self, *args, **kwargs):
        self.placeholder = kwargs.pop('placeholder', None)
        return super(EmailWidget, self).__init__(*args, **kwargs)

    def render(self, name, value, attrs=None):
        attrs = attrs or {}
        if self.placeholder:
            attrs['placeholder'] = self.placeholder
        return super(EmailWidget, self).render(name, value, attrs)


class ColorWidget(Input):
    """HTML5 color type."""

    input_type = 'color'

    def __init__(self, *args, **kwargs):
        self.placeholder = kwargs.pop('placeholder', None)
        return super(ColorWidget, self).__init__(*args, **kwargs)

    def render(self, name, value, attrs=None):
        attrs = attrs or {}
        if self.placeholder:
            attrs['placeholder'] = self.placeholder
        return super(ColorWidget, self).render(name, value, attrs)
