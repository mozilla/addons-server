# ruff: noqa: F405
from olympia.lib.settings_base import *  # noqa


ENGAGE_ROBOTS = False

EMAIL_URL = env.email_url('EMAIL_URL')
EMAIL_HOST = EMAIL_URL['EMAIL_HOST']
EMAIL_PORT = EMAIL_URL['EMAIL_PORT']
EMAIL_BACKEND = EMAIL_URL['EMAIL_BACKEND']
EMAIL_HOST_USER = EMAIL_URL['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = EMAIL_URL['EMAIL_HOST_PASSWORD']

RAISE_ON_SIGNAL_ERROR = True

API_THROTTLING = True

DOMAIN = env('DOMAIN', default='addons-dev.allizom.org')
SERVICES_DOMAIN = env('SERVICES_DOMAIN', default='services.addons-dev.allizom.org')
SERVER_EMAIL = 'zdev@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
INTERNAL_SITE_URL = env('INTERNAL_SITE_URL', default='https://addons-dev.allizom.org')
EXTERNAL_SITE_URL = env('EXTERNAL_SITE_URL', default='https://addons-dev.allizom.org')
SERVICES_URL = 'https://' + SERVICES_DOMAIN
STATIC_URL = '%s/static-server/' % EXTERNAL_SITE_URL
MEDIA_URL = '%s/user-media/' % EXTERNAL_SITE_URL

CONTENT_SECURITY_POLICY['DIRECTIVES']['font-src'] += (STATIC_URL,)
# img-src already contains 'self', but we could be on reviewers or admin
# domain and want to load things from the regular domain.
CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src'] += (MEDIA_URL, STATIC_URL)
CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src'] += (STATIC_URL,)
CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src'] += (STATIC_URL,)

SESSION_COOKIE_DOMAIN = '.%s' % DOMAIN

# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN', default='addons-dev.allizom.org')

DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
    'replica': get_db_config('DATABASES_REPLICA_URL', atomic_requests=False),
}

REPLICA_DATABASES = ['replica']

# Celery
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Update the logger name used for mozlog
LOGGING['formatters']['json']['logger_name'] = 'http_app_addons_dev'

ES_TIMEOUT = 60
ES_INDEXES = {k: f'{v}_{ENV}' for k, v in ES_INDEXES.items()}

# --enable-background-service-worker linter flag value
ADDONS_LINTER_ENABLE_SERVICE_WORKER = True

ALLOW_SELF_REVIEWS = True

FXA_CONFIG = {
    **FXA_CONFIG,
    'local': {
        'client_id': env('DEVELOPMENT_FXA_CLIENT_ID'),
        'client_secret': env('DEVELOPMENT_FXA_CLIENT_SECRET'),
        # fxa redirects to http://localhost:3000/api/auth/authenticate-callback/?config=local  # noqa
    },
}
FXA_CONTENT_HOST = 'https://accounts.stage.mozaws.net'
FXA_OAUTH_HOST = 'https://oauth.stage.mozaws.net/v1'
FXA_PROFILE_HOST = 'https://profile.stage.mozaws.net/v1'

SITEMAP_DEBUG_AVAILABLE = True

ENABLE_ADMIN_MLBF_UPLOAD = True

SWAGGER_UI_ENABLED = True
