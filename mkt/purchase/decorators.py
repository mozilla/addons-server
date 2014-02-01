import functools

from django.core.exceptions import PermissionDenied

import commonware.log

log = commonware.log.getLogger('mkt.purchase')


def can_become_premium(f):
    """Check that the webapp can become premium."""
    @functools.wraps(f)
    def wrapper(request, addon_id, addon, *args, **kw):
        if not addon.can_become_premium():
            log.info('Cannot become premium: %d' % addon.pk)
            raise PermissionDenied
        return f(request, addon_id, addon, *args, **kw)
    return wrapper


def can_be_purchased(f):
    """
    Check if it can be purchased, returns False if not premium.
    Must be called after the addon_view decorator.
    """
    @functools.wraps(f)
    def wrapper(request, addon, *args, **kw):
        if not addon.can_be_purchased():
            log.info('Cannot be purchased: %d' % addon.pk)
            raise PermissionDenied
        return f(request, addon, *args, **kw)
    return wrapper


def has_purchased(f):
    """
    If the addon is premium, require a purchase.
    Must be called after addon_view decorator.
    """
    @functools.wraps(f)
    def wrapper(request, addon, *args, **kw):
        if addon.is_premium() and not addon.has_purchased(request.amo_user):
            log.info('Not purchased: %d' % addon.pk)
            raise PermissionDenied
        return f(request, addon, *args, **kw)
    return wrapper
