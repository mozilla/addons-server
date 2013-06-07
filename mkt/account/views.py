import jingo

import amo
from amo.decorators import login_required
from devhub.views import _get_items


@login_required
def activity_log(request, userid):
    all_apps = request.amo_user.addons.filter(type=amo.ADDON_WEBAPP)
    return jingo.render(request, 'account/activity.html',
                        {'log': _get_items(None, all_apps)})
