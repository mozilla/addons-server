from django import http
from django.shortcuts import redirect
from django.utils.encoding import smart_unicode as u

from amo.helpers import page_title

from . import SERVICES
from .forms import ShareForm


def share(request, obj, name, description):
    try:
        service = SERVICES[request.GET['service']]
    except KeyError:
        raise http.Http404()
    is_webapp = hasattr(obj, 'is_webapp') and obj.is_webapp()

    form = ShareForm({
        'title': page_title({'request': request}, name,
                            force_webapps=is_webapp),
        'url': u(obj.get_url_path()),
        'description': u(description),
    })
    form.full_clean()
    return redirect(service.url.format(**form.cleaned_data))
