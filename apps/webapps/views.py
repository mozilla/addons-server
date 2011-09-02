from django.shortcuts import get_object_or_404

import addons.views

from .models import Webapp


def app_detail(request, app_slug):
    # TODO: check status.
    webapp = get_object_or_404(Webapp, app_slug=app_slug)
    return addons.views.extension_detail(request, webapp)
