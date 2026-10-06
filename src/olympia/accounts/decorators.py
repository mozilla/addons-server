import functools
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.core.signing import TimestampSigner
from django.urls import reverse

import waffle

import olympia.core.logger
from olympia.accounts.utils import redirect_for_login_with_2fa_enforced


# Needs to match accounts/views.py
log = olympia.core.logger.getLogger('accounts')


def reprompt_for_2fa_if_necessary(request):
    """Return None if reprompting for 2FA is not enforced or necessary for this
    request, or an HttpResponse redirecting to login prompting for that 2FA."""
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
        next_path = None
        if (
            should_reprompt_2fa
            and request.user.is_authenticated
            and request.method == 'POST'
            # Only content-type: multipart/form-data: we're going to store the
            # data in session, we don't want to serialize uploads...
            and request.headers.get('Content-Type') != 'multipart/form-data'
        ):
            # If the user is unlucky they might get the reprompt when doing a
            # POST rather than a GET. If we just redirected to FxA here, they
            # would lose the contents of their POST. To work around that, store
            # the post data in the session temporarily, and redirect to a
            # special URL that would restore it by presenting a new form with
            # that data filled in.
            # Because of the potential size, we don't do that if there was an
            # upload though, in that case they will need to start again after
            # logging in.
            # The post data is stored with a unique key; we sign that key with
            # a timestamp and pass that to the callback URL, it should verify
            # that it's valid and within an acceptable time period before
            # restoring the post data.
            key = f'{request.user.pk}:{uuid.uuid4().hex}'
            signature = TimestampSigner().sign(key)
            next_path = f'{reverse("auth:accounts.restore-post")}?s={signature}'
            request.session['_post_data_after_2fa_reprompt'] = {
                'url': request.path,
                'key': key,
                'data': request.POST.urlencode(),
            }
        log.info('Redirecting user %s to enforce 2FA', request.user)
        return redirect_for_login_with_2fa_enforced(
            request, next_path=next_path, login_hint=login_hint
        )
    return None


def two_factor_auth_required(f):
    """Require the user to be authenticated and have 2FA enabled.

    If 2fa-reprompt waffle switch is enabled, this also requires the user to
    have authenticated through FxA recently (with 2FA)."""

    @functools.wraps(f)
    def wrapper(request, *args, **kw):
        response = reprompt_for_2fa_if_necessary(request)
        if response is not None:
            return response
        else:
            return f(request, *args, **kw)

    return wrapper
