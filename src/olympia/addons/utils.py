import uuid
import json
import zipfile

from io import BytesIO
from urllib.parse import urlparse

from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import File
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.transaction import atomic
from django.utils import translation
from django.utils.translation import gettext

from django_statsd.clients import statsd

from olympia import amo, core
from olympia.access.acl import action_allowed_user
from olympia.amo.utils import normalize_string
from olympia.constants.site_permissions import SITE_PERMISSION_MIN_VERSION
from olympia.discovery.utils import call_recommendation_server
from olympia.translations.fields import LocaleErrorMessage
from olympia.translations.models import Translation
from olympia.users.models import (
    DeveloperAgreementRestriction,
    UserRestrictionHistory,
)
from olympia.users.utils import get_task_user


log = core.logger.getLogger('z.addons')


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


class SitePermissionVersionCreator:
    """Helper class to create new site permission add-ons and versions.

    Assumes parameters have already been validated beforehand."""

    def __init__(self, *, user, remote_addr, install_origins, site_permissions):
        self.user = user
        self.remote_addr = remote_addr
        self.install_origins = sorted(install_origins or [])
        self.site_permissions = site_permissions

    def _create_manifest(self, version_number, guid=None):

        hostnames = ', '.join(
            [urlparse(origin).netloc for origin in self.install_origins]
        )
        if guid is None:
            guid = generate_addon_guid()
        # FIXME: https://github.com/mozilla/addons-server/issues/18421 to
        # generate translations for the name (we'll need __MSG_extensionName__
        # and _locales/ folder etc). At the moment the gettext() call is just
        # here to prepare for the future and allow translators to work on
        # translations, but we're always generating in english.
        with translation.override('en-US'):
            manifest_data = {
                'manifest_version': 2,
                'version': version_number,
                'name': gettext('Site permissions for {hostnames}').format(
                    hostnames=hostnames
                ),
                'install_origins': self.install_origins,
                'site_permissions': self.site_permissions,
                'browser_specific_settings': {
                    'gecko': {
                        'id': guid,
                        'strict_min_version': SITE_PERMISSION_MIN_VERSION,
                    }
                },
            }
        return manifest_data

    def _create_zipfile(self, manifest_data):
        # Create the xpi containing the manifest, in memory.
        raw_buffer = BytesIO()
        with zipfile.ZipFile(raw_buffer, 'w') as zip_file:
            zip_file.writestr('manifest.json', json.dumps(manifest_data, indent=2))
        raw_buffer.seek(0)
        filename = 'automatic.xpi'
        file_obj = File(raw_buffer, filename)

        return file_obj

    @atomic
    def create_version(self, addon=None):
        from olympia.addons.models import Addon
        from olympia.files.models import FileUpload
        from olympia.files.utils import parse_addon
        from olympia.versions.models import Version
        from olympia.versions.utils import get_next_version_number

        version_number = '1.0'
        guid = None

        # If passing an existing add-on, we need to bump the version number
        # to avoid clashes, and also perform a few checks.
        if addon is not None:
            # Obviously we want an add-on with the right type.
            if addon.type != amo.ADDON_SITE_PERMISSION:
                raise ImproperlyConfigured(
                    'SitePermissionVersionCreator was instantiated with non '
                    'site-permission add-on'
                )
            # If the user isn't an author, something is wrong.
            if not addon.authors.filter(pk=self.user.pk).exists():
                raise ImproperlyConfigured(
                    'SitePermissionVersionCreator was instantiated with a '
                    'bogus addon/user'
                )
            # Changing the origins isn't supported at the moment.
            latest_version = addon.find_latest_version(
                exclude=(), channel=amo.RELEASE_CHANNEL_UNLISTED
            )
            previous_origins = sorted(
                latest_version.installorigin_set.all().values_list('origin', flat=True)
            )
            if previous_origins != self.install_origins:
                raise ImproperlyConfigured(
                    'SitePermissionVersionCreator was instantiated with an '
                    'addon that has different origins'
                )

            version_number = get_next_version_number(addon)
            guid = addon.guid

        # Create the manifest, with more user-friendly name & description built
        # from install_origins/site_permissions, and then the zipfile with that
        # manifest inside.
        manifest_data = self._create_manifest(version_number, guid=guid)
        file_obj = self._create_zipfile(manifest_data)

        # Parse the zip we just created. The user needs to be the Mozilla User
        # because regular submissions of this type of add-on is forbidden to
        # normal users.
        parsed_data = parse_addon(
            file_obj,
            addon=addon,
            user=get_task_user(),
        )

        with core.override_remote_addr(self.remote_addr):
            if addon is None:
                # Create the Addon instance (without a Version/File at this point).
                addon = Addon.initialize_addon_from_upload(
                    data=parsed_data,
                    upload=file_obj,
                    channel=amo.RELEASE_CHANNEL_UNLISTED,
                    user=self.user,
                )

            # Create the FileUpload that will become the File+Version.
            upload = FileUpload.from_post(
                file_obj,
                filename=file_obj.name,
                size=file_obj.size,
                addon=addon,
                version=version_number,
                channel=amo.RELEASE_CHANNEL_UNLISTED,
                user=self.user,
                source=amo.UPLOAD_SOURCE_GENERATED,
            )

        # And finally create the Version instance from the FileUpload.
        return Version.from_upload(
            upload,
            addon,
            amo.RELEASE_CHANNEL_UNLISTED,
            selected_apps=[x[0] for x in amo.APPS_CHOICES],
            parsed_data=parsed_data,
        )


def fetch_translations_from_addon(addon, properties):
    translation_ids_gen = (getattr(addon, prop + '_id', None) for prop in properties)
    translation_ids = [id_ for id_ in translation_ids_gen if id_]
    # Just get all the values together to make it simplier
    return {str(value) for value in Translation.objects.filter(id__in=translation_ids)}


class DeleteTokenSigner(TimestampSigner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **{'salt': 'addon-delete', **kwargs})

    def generate(self, addon_id):
        return self.sign_object({'addon_id': addon_id})

    def validate(self, token, addon_id):
        try:
            token_payload = self.unsign_object(token, max_age=60)
        except (SignatureExpired, BadSignature) as exc:
            log.debug(exc)
            return False
        return token_payload['addon_id'] == addon_id
