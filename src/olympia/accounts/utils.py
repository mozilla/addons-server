import binascii
import os

from base64 import urlsafe_b64encode
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.encoding import force_str

from olympia.amo.utils import is_safe_url, use_fake_fxa


def fxa_login_url(
    config,
    state,
    next_path=None,
    action=None,
    force_two_factor=False,
    request=None,
    id_token=None,
):
    if next_path and is_safe_url(next_path, request):
        state += ':' + force_str(urlsafe_b64encode(next_path.encode('utf-8'))).rstrip(
            '='
        )
    query = {
        'client_id': config['client_id'],
        'scope': 'profile openid',
        'state': state,
        'access_type': 'offline',
    }
    if action is not None:
        query['action'] = action
    if force_two_factor is True:
        # Specifying AAL2 will require the token to have an authentication
        # assurance level >= 2 which corresponds to requiring 2FA.
        query['acr_values'] = 'AAL2'
        # Requesting 'prompt=none' during authorization, together with passing
        # a valid id token in 'id_token_hint', allows the user to not have to
        # re-authenticate with FxA if they still have a valid session (which
        # they should here: they went through FxA, back to AMO, and now we're
        # redirecting them to FxA because we want them to have 2FA enabled).
        if id_token:
            query['prompt'] = 'none'
            query['id_token_hint'] = id_token
    if use_fake_fxa():
        base_url = reverse('fake-fxa-authorization')
    else:
        base_url = f'{settings.FXA_OAUTH_HOST}/authorization'
    return f'{base_url}?{urlencode(query)}'


def generate_fxa_state():
    return force_str(binascii.hexlify(os.urandom(32)))


def redirect_for_login(request):
    request.session.setdefault('fxa_state', generate_fxa_state())
    url = fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path_with_query(request),
        action='signin',
    )
    return HttpResponseRedirect(url)


def path_with_query(request):
    next_path = request.path
    qs = request.GET.urlencode()
    if qs:
        return f'{next_path}?{qs}'
    else:
        return next_path
