import jingo

from commonware.response.decorators import xframe_allow

def home(request):
    return jingo.render(request, 'offline/home.html', {'request': request})

@xframe_allow
def stub(request):
    return jingo.render(request, 'offline/stub.html', {'request': request})
