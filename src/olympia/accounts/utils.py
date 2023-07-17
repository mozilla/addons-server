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
    enforce_two_factor_authentication=False,
    request=None,
    id_token_hint=None,
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
    if enforce_two_factor_authentication is True:
        # Specifying AAL2 will require the token to have an authentication
        # assurance level >= 2 which corresponds to requiring 2FA.
        query['acr_values'] = 'AAL2'
        # Requesting 'prompt=none' during authorization allows the user to not
        # have to re-authenticate with FxA if they still have a valid session,
        # in case they just went through FxA, then back to AMO only to find out
        # we are requiring 2FA. To let FxA know who the user should be, we pass
        # id_token_hint, which we have in this specific case.
        # If we didn't just go through authentication, that means the user was
        # alraedy logged in but we enforced 2FA at a later stage. We don't have
        # id_token_hint, but we can pass login_hint instead.
        # FIXME: this doesn't work, getting redirected to our callback with an
        # unauthorized_client error from FxA. According to the docs usage of
        # id_token_hint is always allowed but login_hint isn't, so we need to
        # have our oauth client configs be explicitly allowed.
        # https://mozilla.github.io/ecosystem-platform/reference/oauth-details
        # #promptnone-support
        # FIXME: this highlights the fact that we need to handle error cases
        # and regenerate a new state to start from scratch - right now we're
        # ignoring them, so the user can't recover. I'm not sure what's
        # supposed to happen if the user goes to FxA with prompt=none and
        # login_hint=email if they no longer have a valid FxA session (ideally
        # FxA would handle that gracefully), but if an error is raised we'll
        # need to handle it.
        if id_token_hint:
            query['prompt'] = 'none'
            query['id_token_hint'] = id_token_hint
        elif request and request.user.is_authenticated:
            query['prompt'] = 'none'
            query['login_hint'] = request.user.email
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


def redirect_for_login_with_two_factor_authentication(
    request, *, config=None, next_path=None, id_token_hint=None
):
    if config is None:
        config = settings.FXA_CONFIG['default']
    if next_path is None:
        next_path = path_with_query(request)
    request.session.setdefault('fxa_state', generate_fxa_state())
    request.session['enforce_two_factor_authentication'] = True
    url = fxa_login_url(
        config=config,
        state=request.session['fxa_state'],
        next_path=next_path,
        action='signin',
        enforce_two_factor_authentication=True,
        id_token_hint=id_token_hint,
    )
    return HttpResponseRedirect(url)


def path_with_query(request):
    next_path = request.path
    qs = request.GET.urlencode()
    if qs:
        return f'{next_path}?{qs}'
    else:
        return next_path
