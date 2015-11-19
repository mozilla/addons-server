import logging

import requests

log = logging.getLogger('accounts.verify')
IdentificationError = LookupError


def fxa_identify(code, config=None):
    """Get an FxA profile for an access token. If identification fails an
    IdentificationError is raised."""
    token = get_fxa_token(code, config)['access_token']
    return get_fxa_profile(token, config)


def get_fxa_token(code, config):
    log.debug('Getting token [{code}]'.format(code=code))
    response = requests.post(config['oauth_uri'] + '/token', data={
        'code': code,
        'client_id': config['client_id'],
        'client_secret': config['client_secret'],
    })
    if response.status_code == 200:
        data = response.json()
        if data.get('access_token'):
            log.debug('Got token {data} [{code}]'.format(data=data, code=code))
            return data
        else:
            log.info('No token returned {data} [{code}]'.format(data=data,
                                                                code=code))
            raise IdentificationError(
                'No access token returned for {code}'.format(code=code))
    else:
        log.info('Token returned non-200 status {status} [{code}]'.format(
            code=code, status=response.status_code))
        raise IdentificationError(
            'Could not get access token for {code}'.format(code=code))


def get_fxa_profile(token, config):
    log.debug('Getting profile [{token}]'.format(token=token))
    response = requests.get(config['profile_uri'] + '/profile', headers={
        'Authorization': 'Bearer {token}'.format(token=token),
    })
    if response.status_code == 200:
        profile = response.json()
        if profile.get('email'):
            log.debug('Got profile {profile} [{token}]'.format(profile=profile,
                                                               token=token))
            return profile
        else:
            log.info('Incomplete profile {profile} [{token}]'.format(
                profile=profile, token=token))
            raise IdentificationError('Profile incomplete for {token}'.forat(
                token=token))
    else:
        log.info('Profile returned non-200 status {status} [{token}]'.format(
            token=token, status=response.status_code))
        raise IdentificationError('Could not find profile for {token}'.format(
            token=token))
