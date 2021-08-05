import uuid

from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext

from django_statsd.clients import statsd

from olympia import amo
from olympia.access.acl import action_allowed_user
from olympia.amo.utils import normalize_string
from olympia.discovery.utils import call_recommendation_server
from olympia.translations.fields import LocaleErrorMessage
from olympia.users.models import DeveloperAgreementRestriction, UserRestrictionHistory


def generate_addon_guid():
    return '{%s}' % str(uuid.uuid4())


def verify_mozilla_trademark(name, user, form=None):
    skip_trademark_check = (
        user
        and user.is_authenticated
        and action_allowed_user(user, amo.permissions.TRADEMARK_BYPASS)
    )

    def _check(name):
        name = normalize_string(name, strip_punctuation=True).lower()

        for symbol in amo.MOZILLA_TRADEMARK_SYMBOLS:
            violates_trademark = name.count(symbol) > 1 or (
                name.count(symbol) >= 1 and not name.endswith(f' for {symbol}')
            )

            if violates_trademark:
                raise forms.ValidationError(
                    gettext(
                        'Add-on names cannot contain the Mozilla or '
                        'Firefox trademarks.'
                    )
                )

    if not skip_trademark_check:
        if not isinstance(name, dict):
            _check(name)
        else:
            for locale, localized_name in name.items():
                try:
                    _check(localized_name)
                except forms.ValidationError as exc:
                    if form is not None:
                        for message in exc.messages:
                            error_message = LocaleErrorMessage(
                                message=message, locale=locale
                            )
                            form.add_error('name', error_message)
                    else:
                        raise
    return name


TAAR_LITE_FALLBACKS = [
    'enhancerforyoutube@maximerf.addons.mozilla.org',  # /enhancer-for-youtube/
    '{2e5ff8c8-32fe-46d0-9fc8-6b8986621f3c}',  # /search_by_image/
    'uBlock0@raymondhill.net',  # /ublock-origin/
    'newtaboverride@agenedia.com',
]  # /new-tab-override/

TAAR_LITE_OUTCOME_REAL_SUCCESS = 'recommended'
TAAR_LITE_OUTCOME_REAL_FAIL = 'recommended_fallback'
TAAR_LITE_OUTCOME_CURATED = 'curated'
TAAR_LITE_FALLBACK_REASON_TIMEOUT = 'timeout'
TAAR_LITE_FALLBACK_REASON_EMPTY = 'no_results'
TAAR_LITE_FALLBACK_REASON_INVALID = 'invalid_results'


def get_addon_recommendations(guid_param, taar_enable):
    guids = None
    fail_reason = None
    if taar_enable:
        guids = call_recommendation_server(
            settings.TAAR_LITE_RECOMMENDATION_ENGINE_URL, guid_param, {}
        )
        outcome = (
            TAAR_LITE_OUTCOME_REAL_SUCCESS if guids else TAAR_LITE_OUTCOME_REAL_FAIL
        )
        if not guids:
            fail_reason = (
                TAAR_LITE_FALLBACK_REASON_EMPTY
                if guids == []
                else TAAR_LITE_FALLBACK_REASON_TIMEOUT
            )
    else:
        outcome = TAAR_LITE_OUTCOME_CURATED
    if not guids:
        guids = TAAR_LITE_FALLBACKS
    return guids, outcome, fail_reason


def is_outcome_recommended(outcome):
    return outcome == TAAR_LITE_OUTCOME_REAL_SUCCESS


def get_addon_recommendations_invalid():
    return (
        TAAR_LITE_FALLBACKS,
        TAAR_LITE_OUTCOME_REAL_FAIL,
        TAAR_LITE_FALLBACK_REASON_INVALID,
    )


def compute_last_updated(addon):
    """Compute the value of last_updated for a single add-on."""
    from olympia.addons.models import Addon

    queries = Addon._last_updated_queries()
    if addon.status == amo.STATUS_APPROVED:
        q = 'public'
    else:
        q = 'exp'
    values = (
        queries[q]
        .filter(pk=addon.pk)
        .using('default')
        .values_list('last_updated', flat=True)
    )
    return values[0] if values else None


class RestrictionChecker:
    """
    Wrapper around all our submission and approval restriction classes.

    To use, instantiate it with the request and call is_submission_allowed(),
    or with None as the request and is_auto_approval_allowed() for approval after
    submission.
    After this method has been called, the error message to show the user if
    needed will be available through get_error_message()
    """

    # We use UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES because it
    # currently matches the order we want to check things. If that ever
    # changes, keep RESTRICTION_CLASSES_CHOICES current order (to keep existing
    # records intact) but change the `restriction_choices` definition below.
    restriction_choices = UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES

    def __init__(self, *, request=None, upload=None):
        self.request = request
        self.upload = upload
        if self.request:
            self.user = self.request.user
            self.ip_address = self.request.META.get('REMOTE_ADDR', '')
        elif self.upload:
            self.user = self.upload.user
            self.ip_address = self.upload.ip_address
        else:
            raise ImproperlyConfigured('RestrictionChecker needs a request or upload')
        self.failed_restrictions = []

    def _is_action_allowed(self, action_type, *, restriction_choices=None):
        if restriction_choices is None:
            restriction_choices = self.restriction_choices
        argument = None
        if action_type == 'submission':
            argument = self.request
        elif action_type == 'auto_approval':
            argument = self.upload
        for restriction_number, cls in restriction_choices:
            if not hasattr(cls, f'allow_{action_type}'):
                continue
            allowed_method = getattr(cls, f'allow_{action_type}', None)
            if allowed_method is None:
                continue
            allowed = allowed_method(argument)
            if not allowed:
                self.failed_restrictions.append(cls)
                name = cls.__name__
                statsd.incr(
                    f'RestrictionChecker.is_{action_type}_allowed.{name}.failure'
                )
                if self.user and self.user.is_authenticated:
                    UserRestrictionHistory.objects.create(
                        user=self.user,
                        ip_address=self.ip_address,
                        last_login_ip=self.user.last_login_ip or '',
                        restriction=restriction_number,
                    )
        suffix = 'success' if not self.failed_restrictions else 'failure'
        statsd.incr(f'RestrictionChecker.is_{action_type}_allowed.%s' % suffix)
        return not self.failed_restrictions

    def is_submission_allowed(self, check_dev_agreement=True):
        """
        Check whether the `request` passed to the instance is allowed to submit add-ons.
        Will check all classes declared in self.restriction_classes, but ignore those
        that don't have a allow_submission() method.

        Pass check_dev_agreement=False to avoid checking
        DeveloperAgreementRestriction class, which is useful only for the
        developer agreement page itself, where the developer hasn't validated
        the agreement yet but we want to do the other checks anyway.
        """
        if not self.request:
            raise ImproperlyConfigured('Need a request to call is_submission_allowed()')

        if self.user and self.user.bypass_upload_restrictions:
            return True

        if check_dev_agreement is False:
            restriction_choices = filter(
                lambda item: item[1] != DeveloperAgreementRestriction,
                self.restriction_choices,
            )
        else:
            restriction_choices = None
        return self._is_action_allowed(
            'submission', restriction_choices=restriction_choices
        )

    def is_auto_approval_allowed(self):
        """
        Check whether the `upload` passed to the instance is allowed auto-approval.
        Will check all classes declared in self.restriction_classes, but ignore those
        that don't have a allow_auto_approval() method.
        """

        if not self.upload:
            raise ImproperlyConfigured(
                'Need an upload to call is_auto_approval_allowed()'
            )

        return self._is_action_allowed('auto_approval')

    def get_error_message(self):
        """
        Return the error message to show to the user after a call to
        is_submission_allowed_for_request() has been made. Will return the
        message to be displayed to the user, or None if there is no specific
        restriction applying.
        """
        try:
            msg = self.failed_restrictions[0].get_error_message(
                is_api=self.request and self.request.is_api
            )
        except IndexError:
            msg = None
        return msg
