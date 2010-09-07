import jingo
from tower import ugettext as _

from amo.decorators import login_required


def index(request):
    return jingo.render(request, 'devhub/index.html', dict())


# TODO: Check if user is a developer.
@login_required
def addons_activity(request):
    return jingo.render(request, 'devhub/addons_activity.html', dict())
