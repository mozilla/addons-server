import time

from django.conf import settings

import requests

from django_statsd.clients import statsd

import olympia.core.logger
from olympia.amo.utils import use_fake_fxa


log = olympia.core.logger.getLogger('accounts.verify')
IdentificationError = LookupError


def fxa_identify(code, config):
    """Given an FxA access code, return a tuple with the FxA profile dict and the token
    data from FxA, which could contain an OpenID token (unless it somehow wasn't
    present). If identification fails an IdentificationError is raised.

    The OpenID token returned is short-lived, meant to be used with
    `prompt=none` if we need to redirect the user back to FxA immediately and
    don't want them to have to re-authenticate there again."""
    try:
        with statsd.timer('accounts.fxa.identify.all'):
            token_data = get_fxa_token(code=code, config=config)
            profile = get_fxa_profile(token_data['access_token'])
    except Exception:
        statsd.incr('accounts.fxa.identify.all.fail')
        raise
    else:
        statsd.incr('accounts.fxa.identify.all.success')
        return profile, token_data


def get_fxa_token(*, code=None, refresh_token=None, config=None):
    """Given an FxA access code or refresh token, return dict from FxA /token endpoint
    (https://git.io/JJZww). Should at least contain `access_token` and
    `id_token` keys.
    """
    assert config, 'config dict must be provided to get_fxa_token'
    assert (
        code or refresh_token
    ), 'either code or refresh_token must be provided to get_fxa_token'
    log_identifier = f'code:{code}' if code else f'refresh:{refresh_token[:8]}'
    log.info(f'Getting token [{log_identifier}]')
    with statsd.timer('accounts.fxa.identify.token'):
        if code:
            grant_data = {'grant_type': 'authorization_code', 'code': code}
        else:
            grant_data = {'grant_type': 'refresh_token', 'refresh_token': refresh_token}
        response = requests.post(
            settings.FXA_OAUTH_HOST + '/token',
            data={
                **grant_data,
                'client_id': config['client_id'],
                'client_secret': config['client_secret'],
            },
        )
    if response.status_code == 200:
        data = response.json()
        if data.get('access_token'):
            log.info(f'Got token for [{log_identifier}]')
            data['access_token_expiry'] = time.time() + data.get('expires_in', 43200)
            return data
        else:
            log.info(f'No token returned for [{log_identifier}]')
            raise IdentificationError(f'No access token returned for {log_identifier}')
    else:
        log.info(
            'Token returned non-200 status {status} {body} [{code_or_token}]'.format(
                code_or_token=log_identifier,
                status=response.status_code,
                body=response.content,
            )
        )
        raise IdentificationError(f'Could not get access token for {log_identifier}')


def get_fxa_profile(token):
    """Given a FxA access token, return profile information for the
    corresponding user."""
    with statsd.timer('accounts.fxa.identify.profile'):
        response = requests.get(
            settings.FXA_PROFILE_HOST + '/profile',
            headers={
                'Authorization': f'Bearer {token}',
            },
        )
    if response.status_code == 200:
        profile = response.json()
        if profile.get('email'):
            return profile
        else:
            log.info(f'Incomplete profile {profile}')
            raise IdentificationError(f'Profile incomplete for {token}')
    else:
        log.info(
            'Profile returned non-200 status {status} {body}'.format(
                status=response.status_code, body=response.content
            )
        )
        raise IdentificationError(f'Could not find profile for {token}')


def check_and_update_fxa_access_token(request):
    """This function checks access_token_expiry time in `request.session` and refreshes
    the access_token with the refresh token.

    IdentificationError from `get_fxa_token` will be raised if there is a problem
    refreshing, and `request.session` is updated with the new access_token_expiry time
    otherwise."""

    if (
        not use_fake_fxa()
        and settings.VERIFY_FXA_ACCESS_TOKEN
        and (request.session.get('fxa_access_token_expiry') or 0) < time.time()
    ):
        if not request.session.get('fxa_refresh_token'):
            raise IdentificationError(
                'Could not get access token because refresh token missing from session'
            )

        config_name = (
            request.session['fxa_config_name']
            if request.session.get('fxa_config_name') in settings.ALLOWED_FXA_CONFIGS
            else settings.DEFAULT_FXA_CONFIG_NAME
        )

        # This will raise IdentificationError if there is a problem
        token_data = get_fxa_token(
            refresh_token=request.session.get('fxa_refresh_token'),
            config=settings.FXA_CONFIG[config_name],
        )
        request.session['fxa_access_token_expiry'] = token_data['access_token_expiry']
