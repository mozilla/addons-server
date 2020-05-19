from django.conf import settings

import requests

from django_statsd.clients import statsd

import olympia.core.logger


log = olympia.core.logger.getLogger('accounts.verify')
IdentificationError = LookupError


def fxa_identify(code, config=None):
    """Get an FxA profile for an access token. If identification fails an
    IdentificationError is raised."""
    try:
        with statsd.timer('accounts.fxa.identify.all'):
            token = get_fxa_token(code, config)['access_token']
            profile = get_fxa_profile(token, config)
    except Exception:
        statsd.incr('accounts.fxa.identify.all.fail')
        raise
    else:
        statsd.incr('accounts.fxa.identify.all.success')
        return profile


def get_fxa_token(code, config):
    log.info('Getting token [{code}]'.format(code=code))
    with statsd.timer('accounts.fxa.identify.token'):
        response = requests.post(settings.FXA_OAUTH_HOST + '/token', data={
            'code': code,
            'client_id': config['client_id'],
            'client_secret': config['client_secret'],
        })
    if response.status_code == 200:
        data = response.json()
        if data.get('access_token'):
            log.info('Got token [{code}]'.format(code=code))
            return data
        else:
            log.info('No token returned [{code}]'.format(code=code))
            raise IdentificationError(
                'No access token returned for {code}'.format(code=code))
    else:
        log.info(
            'Token returned non-200 status {status} {body} [{code}]'.format(
                code=code, status=response.status_code, body=response.content))
        raise IdentificationError(
            'Could not get access token for {code}'.format(code=code))


def get_fxa_profile(token, config):
    with statsd.timer('accounts.fxa.identify.profile'):
        response = requests.get(
            settings.FXA_PROFILE_HOST + '/profile', headers={
                'Authorization': 'Bearer {token}'.format(token=token),
            }
        )
    if response.status_code == 200:
        profile = response.json()
        if profile.get('email'):
            return profile
        else:
            log.info('Incomplete profile {profile}'.format(profile=profile))
            raise IdentificationError('Profile incomplete for {token}'.format(
                token=token))
    else:
        log.info('Profile returned non-200 status {status} {body}'.format(
            status=response.status_code, body=response.content))
        raise IdentificationError('Could not find profile for {token}'.format(
            token=token))
