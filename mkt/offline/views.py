import jingo

from commonware.response.decorators import xframe_allow

@xframe_allow
def home(request):
    return jingo.render(request, 'offline/home.html',
                        {'request': request, 'OFFLINE_MANIFEST': True})
