import functools

import olympia.core.logger
from olympia.accounts.utils import redirect_for_login_with_2fa_enforced


# Needs to match accounts/views.py
log = olympia.core.logger.getLogger('accounts')


def two_factor_auth_required(f):
    """Require the user to be authenticated and have 2FA enabled."""

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        if not request.session.get(
            'has_two_factor_authentication'
        ):
            # Note: Technically the user might not be logged in or not, it does
            # not matter, if they are they need to go through FxA again anyway.
            login_hint = request.user.email if request.user.is_authenticated else None
            log.info('Redirecting user %s to enforce 2FA', request.user)
            return redirect_for_login_with_2fa_enforced(request, login_hint=login_hint)
        return f(request, *args, **kw)

    return wrapper
