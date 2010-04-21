import jingo


def pane(request, version, os):
    return jingo.render(request, 'discovery/pane.html')
