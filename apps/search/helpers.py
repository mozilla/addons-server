import jingo

from . import forms


@jingo.register.function
def SearchForm(request):
    return forms.SearchForm(request)
