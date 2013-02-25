import functools

from django import http
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

import waffle

from addons.models import Addon
import commonware.log

log = commonware.log.getLogger('mkt.purchase')


def addon_view(f, qs=Addon.objects.all):
    @functools.wraps(f)
    def wrapper(request, addon_id=None, app_slug=None, *args, **kw):
        """Provides an addon given either an addon_id or app_slug."""
        assert addon_id or app_slug, 'Must provide addon_id or app_slug'
        get = lambda **kw: get_object_or_404(qs(), **kw)
        if addon_id and addon_id.isdigit():
            addon = get(id=addon_id)
            # Don't get in an infinite loop if addon.slug.isdigit().
            if addon.slug != addon_id:
                url = request.path.replace(addon_id, addon.slug)
                if request.GET:
                    url += '?' + request.GET.urlencode()
                return http.HttpResponsePermanentRedirect(url)
        elif addon_id:
            addon = get(slug=addon_id)
        elif app_slug:
            addon = get(app_slug=app_slug)
        return f(request, addon, *args, **kw)
    return wrapper


def addon_view_factory(qs):
    # Don't evaluate qs or the locale will get stuck on whatever the server
    # starts with. The addon_view() decorator will call qs with no arguments
    # before doing anything, so lambdas are ok.
    # GOOD: Addon.objects.valid
    # GOOD: lambda: Addon.objects.valid().filter(type=1)
    # BAD: Addon.objects.valid()
    return functools.partial(addon_view, qs=qs)


def can_be_purchased(f):
    """
    Check if it can be purchased, returns False if not premium.
    Must be called after the addon_view decorator.
    """
    @functools.wraps(f)
    def wrapper(request, addon, *args, **kw):
        if not waffle.switch_is_active('marketplace'):
            log.error('Marketplace waffle switch is off')
            raise http.Http404
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


def has_purchased_or_refunded(f):
    """
    If the addon is premium, require a purchase.
    Must be called after addon_view decorator.
    """
    @functools.wraps(f)
    def wrapper(request, addon, *args, **kw):
        if addon.is_premium() and not (addon.has_purchased(request.amo_user) or
                                       addon.is_refunded(request.amo_user)):
            log.info('Not purchased or refunded: %d' % addon.pk)
            raise PermissionDenied
        return f(request, addon, *args, **kw)
    return wrapper


def has_not_purchased(f):
    """ The opposite of has_purchased. """
    @functools.wraps(f)
    def wrapper(request, addon, *args, **kw):
        if addon.is_premium() and addon.has_purchased(request.amo_user):
            log.info('Already purchased: %d' % addon.pk)
            raise PermissionDenied
        return f(request, addon, *args, **kw)
    return wrapper


def can_become_premium(f):
    """Check that the addon can become premium."""
    @functools.wraps(f)
    def wrapper(request, addon_id, addon, *args, **kw):
        if not addon.can_become_premium():
            log.info('Cannot become premium: %d' % addon.pk)
            raise PermissionDenied
        return f(request, addon_id, addon, *args, **kw)
    return wrapper
