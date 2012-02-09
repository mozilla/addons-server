import jingo


def index(request):
    return jingo.render(request, 'hub/index.html')
