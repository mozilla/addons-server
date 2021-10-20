from datetime import datetime, timedelta

from django.conf import settings

import requests

from django_statsd.clients import statsd

import olympia.core.logger
from olympia.users.models import FxaToken


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
            profile = get_fxa_profile(token_data['access_token'], config)
    except Exception:
        statsd.incr('accounts.fxa.identify.all.fail')
        raise
    else:
        statsd.incr('accounts.fxa.identify.all.success')
        return profile, token_data


def get_fxa_token(*, code=None, refresh_token=None, config=None):
    """Given an FxA access code, return dict from FxA /token endpoint
    (https://git.io/JJZww). Should at least contain `access_token` and
    `id_token` keys.
    """
    assert config, 'config dict must be provided to get_fxa_token'
    assert (
        code or refresh_token
    ), 'either code or refresh_token must be provided to get_fxa_token'
    log.info(f'Getting token [{code or refresh_token}]')
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
            log.info(f'Got token for [{code or refresh_token}]')
            return data
        else:
            log.info(f'No token returned for [{code or refresh_token}]')
            raise IdentificationError(
                f'No access token returned for {code or refresh_token}'
            )
    else:
        log.info(
            'Token returned non-200 status {status} {body} [{code_or_token}]'.format(
                code_or_token=(code or refresh_token),
                status=response.status_code,
                body=response.content,
            )
        )
        raise IdentificationError(
            f'Could not get access token for {code or refresh_token}'
        )


def get_fxa_profile(token, config):
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


def get_user_token_from_token_data(token_data, config_name):
    """Return a new (unsaved) FxaToken object from token data."""
    return FxaToken(
        access_token=token_data.get('access_token'),
        access_token_expiry=(
            datetime.now() + timedelta(seconds=token_data.get('expires_in', 43200))
        ),
        refresh_token=token_data.get('refresh_token'),
        config_name=config_name,
    )


def fxa_access_token_is_valid(user, token_pk):
    try:
        token_store = FxaToken.objects.get(user=user, id=token_pk)
        if token_store.is_expired:
            config_name = (
                token_store.config_name
                if token_store.config_name in settings.ALLOWED_FXA_CONFIGS
                else settings.DEFAULT_FXA_CONFIG_NAME
            )
            # if the access token has expired get a new one
            token_data = get_fxa_token(
                refresh_token=token_store.refresh_token,
                config=settings.FXA_CONFIG[config_name],
            )
            new_values = {
                'access_token': token_data.get('access_token'),
                'access_token_expiry': datetime.now()
                + timedelta(seconds=token_data.get('expires_in', 43200)),
            }
            if 'refresh_token' in token_data:
                new_values['refresh_token'] = token_data['refresh_token']
            token_store.update(**new_values)

    except FxaToken.DoesNotExist:
        log.info(f'User token record not found for {user.id} + {token_pk}')
        return False
    except IdentificationError:
        log.info(f'Failed refreshing access_token for {user.id} + {token_pk}')
        return False
    else:
        return True
