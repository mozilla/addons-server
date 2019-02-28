from django import http
from django.db.transaction import non_atomic_requests
from django.utils.translation import ugettext

from olympia.amo.decorators import json_view, login_required
from olympia.amo.utils import escape_all

from .models import UserProfile


@login_required(redirect=False)
@json_view
@non_atomic_requests
def ajax(request):
    """Query for a user matching a given email."""

    if 'q' not in request.GET:
        raise http.Http404()

    data = {'status': 0, 'message': ''}

    email = request.GET.get('q', '').strip()

    if not email:
        data.update(message=ugettext('An email address is required.'))
        return data

    user = UserProfile.objects.filter(email=email)

    msg = ugettext('A user with that email address does not exist.')

    if user:
        data.update(status=1, id=user[0].id, name=user[0].name)
    else:
        data['message'] = msg

    return escape_all(data)
