import amo
from access.acl import check_ownership

from lib.metrics import record_action
from mkt.constants.apps import INSTALL_TYPE_DEVELOPER, INSTALL_TYPE_USER


def install_type(request, app):
    if check_ownership(request, app, require_owner=False,
                       ignore_disabled=True, admin=False):
        return INSTALL_TYPE_DEVELOPER
    return INSTALL_TYPE_USER


def record(request, app):
    amo.log(amo.LOG.INSTALL_ADDON, app)
    domain = app.domain_from_url(app.origin, allow_none=True)
    record_action('install', request, {
        'app-domain': domain,
        'app-id': app.pk,
        'region': request.REGION.slug,
        'anonymous': request.user.is_anonymous(),
    })
