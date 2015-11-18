import requests


def fxa_identify(code, config=None):
    """Get an FxA profile for an access token. If identification fails return
    an empty dict."""
    token = get_fxa_token(code, config).get('access_token')
    if token:
        return get_fxa_profile(token, config)
    else:
        return {}


def get_fxa_token(code, config):
    response = requests.post(config['oauth_uri'] + '/token', data={
        'code': code,
        'client_id': config['client_id'],
        'client_secret': config['client_secret'],
    })
    if response.status_code == 200:
        return response.json()
    else:
        return {}


def get_fxa_profile(token, config):
    response = requests.get(config['profile_uri'] + '/profile', headers={
        'Authorization': 'Bearer {token}'.format(token=token),
    })
    if response.status_code == 200:
        return response.json()
    else:
        return {}
