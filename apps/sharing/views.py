from django import http
from django.shortcuts import redirect
from django.utils.encoding import smart_unicode as u

from amo.helpers import page_title, absolutify
import sharing


def share(request, obj, name, description):
    try:
        service = sharing.SERVICES[request.GET['service']]
    except KeyError:
        raise http.Http404()
    d = {
        'title': page_title({'request': request}, name),
        'description': u(description),
        'url': absolutify(u(obj.get_url_path())),
    }
    return redirect(service.url.format(**d))
