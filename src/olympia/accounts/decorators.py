import functools
from datetime import datetime, timedelta

from django.conf import settings

import waffle

import olympia.core.logger
from olympia.accounts.utils import redirect_for_login_with_2fa_enforced


# Needs to match accounts/views.py
log = olympia.core.logger.getLogger('accounts')


def two_factor_auth_required(f):
    """Require the user to be authenticated and have 2FA enabled.

    If 2fa-reprompt waffle switch is enabled, this also requires the user to
    have authenticated through FxA recently (with 2FA)."""

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        has_2fa = request.session.get('has_two_factor_authentication')
        should_reprompt_2fa = (
            has_2fa
            and (
                datetime.fromtimestamp(request.session.get('fxa_auth_at') or 0)
                + timedelta(seconds=settings.FXA_MAX_AUTH_TIME_BEFORE_MFA_REPROMPT)
                < datetime.now()
            )
            and waffle.switch_is_active('2fa-reprompt')
        )
        if not has_2fa or should_reprompt_2fa:
            # Note: Technically the user might not be logged in or not, it does
            # not matter, if they are they need to go through FxA again anyway.
            # If we are reprompting for 2FA, don't pass login_hint, because we
            # want the user to see which account they are entering their 2FA
            # for.
            login_hint = (
                request.user.email
                if request.user.is_authenticated and not should_reprompt_2fa
                else None
            )
            log.info('Redirecting user %s to enforce 2FA', request.user)
            return redirect_for_login_with_2fa_enforced(request, login_hint=login_hint)
        return f(request, *args, **kw)

    return wrapper
