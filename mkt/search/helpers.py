from jingo import register

from . import forms


@register.function
def SimpleSearchForm(data, *args):
    return forms.SimpleSearchForm(data)
