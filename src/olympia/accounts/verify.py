from django.conf import settings

import requests

from django_statsd.clients import statsd

import olympia.core.logger


log = olympia.core.logger.getLogger('accounts.verify')
IdentificationError = LookupError


def fxa_identify(code, config=None):
    """Given an FxA access code, return a tuple with the FxA profile dict and a
    OpenID token (which can be None if somehow it wasn't present in FxA
    response). If identification fails an IdentificationError is raised.

    The OpenID token returned is short-lived, meant to be used with
    `prompt=none` if we need to redirect the user back to FxA immediately and
    don't want them to have to re-authenticate there again."""
    try:
        with statsd.timer('accounts.fxa.identify.all'):
            data = get_fxa_token(code, config)
            profile = get_fxa_profile(data['access_token'])
    except Exception:
        statsd.incr('accounts.fxa.identify.all.fail')
        raise
    else:
        statsd.incr('accounts.fxa.identify.all.success')
        return profile, data.get('id_token')


def get_fxa_token(code, config):
    """Given an FxA access code, return dict from FxA /token endpoint
    (https://git.io/JJZww). Should at least contain `access_token` and
    `id_token` keys.
    """
    log.info(f'Getting token [{code}]')
    with statsd.timer('accounts.fxa.identify.token'):
        response = requests.post(
            settings.FXA_OAUTH_HOST + '/token',
            data={
                'code': code,
                'client_id': config['client_id'],
                'client_secret': config['client_secret'],
            },
        )
    if response.status_code == 200:
        data = response.json()
        if data.get('access_token'):
            log.info(f'Got token [{code}]')
            return data
        else:
            log.info(f'No token returned [{code}]')
            raise IdentificationError(f'No access token returned for {code}')
    else:
        log.info(
            'Token returned non-200 status {status} {body} [{code}]'.format(
                code=code, status=response.status_code, body=response.content
            )
        )
        raise IdentificationError(f'Could not get access token for {code}')


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
