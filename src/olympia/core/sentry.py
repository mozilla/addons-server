import os
import re
import urllib.parse

from olympia.core.utils import get_version_json


# List of fields to scrub in our custom sentry_before_send() callback.
# /!\ Each value needs to be in lowercase !
SENTRY_SENSITIVE_FIELDS = (
    'email',
    'ip_address',
    'remote_addr',
    'remoteaddresschain',
    'x-forwarded-for',
)


def get_sentry_release():
    version_json = get_version_json() or {}
    version = version_json.get('version') or version_json.get('commit')

    # sentry is loaded before django so we have to read the env directly
    ensure_version = os.environ.get('REQUIRE_SENTRY_VERSION', False)

    if not version and ensure_version:
        raise ValueError('Could not determine version for Sentry release tracking')
    return version


def sentry_before_send(event, hint):
    def _scrub_sensitive_data_recursively(data, name=None):
        # This only works with lists or dicts but we shouldn't need anything
        # else.
        if isinstance(data, (list, dict)):
            items = data.items() if isinstance(data, dict) else enumerate(data)
            for key, value in items:
                data[key] = _scrub_sensitive_data_recursively(value, name=key)
        elif (
            isinstance(data, str)
            and isinstance(name, str)
            and name.lower() in SENTRY_SENSITIVE_FIELDS
        ):
            data = '*** redacted ***'
        return data

    try:
        event = _scrub_sensitive_data_recursively(event)
    except Exception:
        pass
    if 'ip_address' in event.get('user', {}):
        event['user'].pop('ip_address')
    return event


def sentry_before_breadcrumb(crumb, hint):
    try:
        if 'data' not in crumb or 'category' not in crumb:
            return crumb
        # Breadcrumbs are useful, but they can contain sensitive information,
        # and it's usually too late to redact the content because the message
        # has already been formatted. We mark such log statements with an
        # explicit sensitive key in the data and exclude them from breadcrumbs
        # entirely (redacting them would likely be pointless since the message
        # itself is likely the problem).
        if crumb['data'].get('sensitive'):
            return None
        # httplib breadcrumbs are useful and we want to keep them, but
        # sometimes the path of the request contains sensitive info. Instead of
        # removing them as above, we match against the URL and redact only its
        # path.
        pattern = r'^.*\/type\/(?:email|ip)\/.*'
        if crumb['category'] == 'httplib' and re.match(
            pattern, crumb['data'].get('url', '')
        ):
            splitted = urllib.parse.urlsplit(crumb['data']['url'])
            crumb['data']['url'] = urllib.parse.urlunsplit(
                splitted._replace(path='/...redacted...')
            )
    except Exception:
        pass

    return crumb


def get_sentry_config(env):
    # i.e. is_dev will be true on addons-dev and false elsewhere
    is_dev = env('ENV', default='') == 'dev'
    # if SENTRY_TRACES_SAMPLE_RATE is set in an env, and it's not 0, then set up the
    # profiling. If it's not set then we default to 1.0 on dev, and 0.0 elsewhere.
    if sample_rate := env.float('SENTRY_TRACES_SAMPLE_RATE', default=(1.0 * is_dev)):
        extra = {
            'traces_sample_rate': sample_rate,
            '_experiments': {
                # profiles_sample_rate is relative to traces_sample_rate, e.g. if
                # traces_sample_rate is 0.1, we're only sampling 10% for profiling too.
                'profiles_sample_rate': 1.0,
            },
        }
    else:
        extra = {}

    return {
        # This is the DSN to the Sentry service.
        'dsn': env('SENTRY_DSN', default=os.environ.get('SENTRY_DSN')),
        # Automatically configure the release based on git information.
        # This uses our `version.json` file if possible or tries to fetch
        # the current git-sha.
        'release': get_sentry_release(),
        # 'send_default_pii: False (the default) is a little too aggressive for us,
        # so we set it to True and do it ourselves - see SENTRY_SENSITIVE_FIELDS
        # below.
        'send_default_pii': True,
        'before_send': sentry_before_send,
        'before_breadcrumb': sentry_before_breadcrumb,
        **extra,
    }
