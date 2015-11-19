import logging

import requests

log = logging.getLogger('accounts.verify')
ProfileNotFound = LookupError


def fxa_identify(code, config=None):
    """Get an FxA profile for an access token. If identification fails a
    ProfileNotFound error is raised."""
    token = get_fxa_token(code, config)['access_token']
    return get_fxa_profile(token, config)


def get_fxa_token(code, config):
    log.debug('Getting token for {code}'.format(code=code))
    response = requests.post(config['oauth_uri'] + '/token', data={
        'code': code,
        'client_id': config['client_id'],
        'client_secret': config['client_secret'],
    })
    if response.status_code == 200:
        data = response.json()
        if data.get('access_token'):
            log.debug('Got token {data}'.format(data=data))
            return data
        else:
            log.info('No token returned {data}'.format(data=data))
            raise ProfileNotFound('No access token returned')
    else:
        log.info('Token returned non-200 status {status}'.format(
            status=response.status_code))
        raise ProfileNotFound('Could not get access token')


def get_fxa_profile(token, config):
    log.debug('Getting profile for {token}'.format(token=token))
    response = requests.get(config['profile_uri'] + '/profile', headers={
        'Authorization': 'Bearer {token}'.format(token=token),
    })
    if response.status_code == 200:
        profile = response.json()
        if profile.get('email'):
            log.debug('Got profile {profile}'.format(profile=profile))
            return profile
        else:
            log.info('Incomplete profile {profile}'.format(profile=profile))
            raise ProfileNotFound('Profile incomplete')
    else:
        log.info('Profile returned non-200 status {status}'.format(
            status=response.status_code))
        raise ProfileNotFound('Could not find profile')
