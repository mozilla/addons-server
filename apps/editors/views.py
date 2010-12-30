import jingo

from amo.decorators import login_required


@login_required
def home(request):

    #  @TODO: This needs @editor_required!

    return jingo.render(request, 'editors/home.html', {})
