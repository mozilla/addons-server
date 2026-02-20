import binascii
import os
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.encoding import force_str

import waffle

import olympia.core.logger
from olympia import amo
from olympia.activity import log_create


log = olympia.core.logger.getLogger('accounts')


def fxa_login_url(
    config,
    state,
    next_path=None,
    enforce_2fa=False,
    request=None,
    id_token_hint=None,
    login_hint=None,
):
    from olympia.amo.utils import is_safe_url, use_fake_fxa

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
    if enforce_2fa is True:
        # Specifying AAL2 will require the token to have an authentication
        # assurance level >= 2 which corresponds to requiring 2FA.
        query['acr_values'] = 'AAL2'
        # https://mozilla.github.io/ecosystem-platform/reference/oauth-details
        # #promptnone-support
        # Requesting 'prompt=none' during authorization allows the user to not
        # have to re-authenticate with FxA if they still have a valid session.
        # We have 2 use cases for this:
        # - The user just logged in through FxA without 2FA, was redirected
        #   back to AMO where we noticed they are a developer and are requiring
        #   2FA for their account. We have id_token_hint in that case that we
        #   pass down.
        # - The user was already logged in but we enforced 2FA on a specific
        #   view they tried to access. We don't have id_token_hint in that case
        #   but our clients are explicitly allowed to pass login_hint instead
        #   (See https://mozilla-hub.atlassian.net/browse/SVCSE-1358).
        # In both cases, the user should then see the 2FA enrollment flow when
        # they get redirected back to FxA.
        if id_token_hint:
            query['prompt'] = 'none'
            query['id_token_hint'] = id_token_hint
        elif login_hint:
            query['prompt'] = 'none'
            query['login_hint'] = login_hint
    if use_fake_fxa(config):
        base_url = reverse('fake-fxa-authorization')
    else:
        base_url = f'{settings.FXA_OAUTH_HOST}/authorization'
    return f'{base_url}?{urlencode(query)}'


def generate_fxa_state():
    return force_str(binascii.hexlify(os.urandom(32)))


def get_fxa_config_name(request):
    config_name = request.GET.get('config')
    if config_name not in settings.FXA_CONFIG:
        if config_name:
            log.info(f'Using default FxA config instead of {config_name}')
        config_name = settings.DEFAULT_FXA_CONFIG_NAME
    return config_name


def get_fxa_config(request):
    return settings.FXA_CONFIG[get_fxa_config_name(request)]


def redirect_for_login(request, *, next_path=None):
    config = get_fxa_config(request)
    if next_path is None:
        next_path = path_with_query(request)
    request.session.setdefault('fxa_state', generate_fxa_state())
    # Previous page in session might have required 2FA, but this page doesn't.
    # We override it in case the user didn't complete the flow for the previous
    # page they were on.
    request.session['enforce_2fa'] = False
    url = fxa_login_url(
        config=config,
        state=request.session['fxa_state'],
        next_path=next_path,
    )
    return HttpResponseRedirect(url)


def redirect_for_login_with_2fa_enforced(
    request, *, config=None, next_path=None, id_token_hint=None, login_hint=None
):
    if config is None:
        config = get_fxa_config(request)
    if next_path is None:
        next_path = path_with_query(request)
    request.session.setdefault('fxa_state', generate_fxa_state())
    request.session['enforce_2fa'] = True
    url = fxa_login_url(
        config=config,
        state=request.session['fxa_state'],
        next_path=next_path,
        enforce_2fa=True,
        id_token_hint=id_token_hint,
        login_hint=login_hint,
        request=request,
    )
    return HttpResponseRedirect(url)


def path_with_query(request):
    next_path = request.path
    qs = request.GET.urlencode()
    if qs:
        return f'{next_path}?{qs}'
    else:
        return next_path


def check_for_session_anomaly(*, session, headers, user):
    """
    Check that session is consistent with the given headers for a user by
    comparing specific headers we store in the session, and record a log if
    they differ.

    Note: we explicitly avoid passing a request object to that function
    to ensure the caller knew what they were doing - depending on the caller
    request.user or request.session might not be set yet.
    """
    REQUEST_HEADERS_KEY = 'request_headers'
    SESSION_ANOMALIES_KEY = 'session_anomalies'
    # Our CDN/WAF is configured to send all of these headers in production,
    # even Cloudfront-viewer-country (backwards-compatility even if we're no
    # longer on Cloudfront).
    REQUEST_HEADERS_TO_CHECK = ('Client-JA4', 'Cloudfront-Viewer-Country', 'Ohfp')

    if not user or not user.is_authenticated:
        return

    if not waffle.switch_is_active('enable-session-anomaly-recording'):
        return

    initial_request = False
    session_request_headers = session.get(REQUEST_HEADERS_KEY)
    if session_request_headers is None:
        initial_request = True
        session_request_headers = {}

    anomalies = []
    for header in REQUEST_HEADERS_TO_CHECK:
        # HTTP headers are case-insensitive, we arbitrarily store them in
        # lowercase in the session.
        session_data_key = header.lower()
        session_data_value = session_request_headers.get(session_data_key)
        header_value = headers.get(header)
        if header_value:
            # Don't consider empty session data for a given header as an
            # anomaly: we might change the list of headers later while not
            # invalidating existing sessions.
            if session_data_value and header_value != session_data_value:
                anomalies.append(
                    {
                        'header': session_data_key,
                        'expected': session_data_value,
                        'received': header_value,
                    }
                )
            session_request_headers[session_data_key] = header_value

    if initial_request:
        session[REQUEST_HEADERS_KEY] = session_request_headers

    if anomalies:
        details = {'anomalies': anomalies}
        log.warning(
            'Session anomaly detected for user %s', user.pk, extra=dict(details)
        )
        if SESSION_ANOMALIES_KEY not in session:
            # Record an activity log about anomalies for this session, but only
            # once per session.
            log_create(amo.LOG.SESSION_ANOMALY, user=user, details=details)
        session[SESSION_ANOMALIES_KEY] = anomalies

    if initial_request or anomalies:
        session.save()
