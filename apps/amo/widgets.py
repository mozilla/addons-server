from django.forms.widgets import Input


class EmailWidget(Input):
    """HTML5 email type."""
    input_type = 'email'

    def __init__(self, *args, **kwargs):
        self.placeholder = kwargs.pop('placeholder', None)
        return super(EmailWidget, self).__init__(*args, **kwargs)

    def render(self, name, value, attrs=None):
        attrs = attrs or {}
        attrs['placeholder'] = self.placeholder
        return super(EmailWidget, self).render(name, value, attrs)
