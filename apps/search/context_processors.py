from .forms import SearchForm


def search_form(request):
    return {'search_form': SearchForm(request)}
