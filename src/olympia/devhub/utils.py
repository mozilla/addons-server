import uuid

import waffle

from celery import chain, chord
from django.conf import settings
from django.forms import ValidationError
from django.utils.translation import ugettext

from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo, core
from olympia.amo.urlresolvers import linkify_and_clean
from olympia.files.models import File, FileUpload
from olympia.files.tasks import repack_fileupload
from olympia.files.utils import parse_addon, parse_xpi
from olympia.scanners.tasks import run_customs, run_wat, run_yara, call_ml_api
from olympia.tags.models import Tag
from olympia.translations.models import Translation
from olympia.users.models import (
    DeveloperAgreementRestriction, UserRestrictionHistory
)
from olympia.versions.utils import process_color_value

from . import tasks


log = olympia.core.logger.getLogger('z.devhub')


def process_validation(validation, is_compatibility=False, file_hash=None,
                       channel=amo.RELEASE_CHANNEL_LISTED):
    """Process validation results into the format expected by the web
    frontend, including transforming certain fields into HTML,  mangling
    compatibility messages, and limiting the number of messages displayed."""
    validation = fix_addons_linter_output(validation, channel=channel)

    if is_compatibility:
        mangle_compatibility_messages(validation)

    # Set an ending tier if we don't have one (which probably means
    # we're dealing with mock validation results or the addons-linter).
    validation.setdefault('ending_tier', 0)

    if not validation['ending_tier'] and validation['messages']:
        validation['ending_tier'] = max(msg.get('tier', -1)
                                        for msg in validation['messages'])

    limit_validation_results(validation)

    htmlify_validation(validation)

    return validation


def mangle_compatibility_messages(validation):
    """Mangle compatibility messages so that the message type matches the
    compatibility type, and alter totals as appropriate."""

    compat = validation['compatibility_summary']
    for k in ('errors', 'warnings', 'notices'):
        validation[k] = compat[k]

    for msg in validation['messages']:
        if msg['compatibility_type']:
            msg['type'] = msg['compatibility_type']


def limit_validation_results(validation):
    """Limit the number of messages displayed in a set of validation results,
    and if truncation has occurred, add a new message explaining so."""

    messages = validation['messages']
    lim = settings.VALIDATOR_MESSAGE_LIMIT
    if lim and len(messages) > lim:
        # Sort messages by severity first so that the most important messages
        # are the one we keep.
        TYPES = {'error': 0, 'warning': 2, 'notice': 3}

        def message_key(message):
            return TYPES.get(message.get('type'))
        messages.sort(key=message_key)

        leftover_count = len(messages) - lim
        del messages[lim:]

        # The type of the truncation message should be the type of the most
        # severe message in the results.
        if validation['errors']:
            msg_type = 'error'
        elif validation['warnings']:
            msg_type = 'warning'
        else:
            msg_type = 'notice'

        compat_type = (msg_type if any(msg.get('compatibility_type')
                                       for msg in messages)
                       else None)

        message = ugettext(
            'Validation generated too many errors/warnings so %s '
            'messages were truncated. After addressing the visible '
            'messages, you\'ll be able to see the others.') % leftover_count

        messages.insert(0, {
            'tier': 1,
            'type': msg_type,
            # To respect the message structure, see bug 1139674.
            'id': ['validation', 'messages', 'truncated'],
            'message': message,
            'description': [],
            'compatibility_type': compat_type})


def htmlify_validation(validation):
    """Process the `message` and `description` fields into
    safe HTML, with URLs turned into links."""

    for msg in validation['messages']:
        msg['message'] = linkify_and_clean(msg['message'])

        if 'description' in msg:
            # Description may be returned as a single string, or list of
            # strings. Turn it into lists for simplicity on the client side.
            if not isinstance(msg['description'], (list, tuple)):
                msg['description'] = [msg['description']]

            msg['description'] = [
                linkify_and_clean(text) for text in msg['description']]


def fix_addons_linter_output(validation, channel):
    """Make sure the output from the addons-linter is the same as amo-validator
    for backwards compatibility reasons."""
    if 'messages' in validation:
        # addons-linter doesn't contain this, return the original validation
        # untouched
        return validation

    def _merged_messages():
        for type_ in ('errors', 'notices', 'warnings'):
            for msg in validation[type_]:
                # FIXME: Remove `uid` once addons-linter generates it
                msg['uid'] = uuid.uuid4().hex
                msg['type'] = msg.pop('_type')
                msg['id'] = [msg.pop('code')]
                # We don't have the concept of tiers for the addons-linter
                # currently
                msg['tier'] = 1
                yield msg

    identified_files = {
        name: {'path': path}
        for name, path in validation['metadata'].get('jsLibs', {}).items()
    }

    # Essential metadata.
    metadata = {
        'listed': channel == amo.RELEASE_CHANNEL_LISTED,
        'identified_files': identified_files,
        'is_webextension': True,
    }
    # Add metadata already set by the linter.
    metadata.update(validation.get('metadata', {}))

    return {
        'success': not validation['errors'],
        'compatibility_summary': {
            'warnings': 0,
            'errors': 0,
            'notices': 0,
        },
        'notices': validation['summary']['notices'],
        'warnings': validation['summary']['warnings'],
        'errors': validation['summary']['errors'],
        'messages': list(_merged_messages()),
        'metadata': metadata,
        'ending_tier': 5,
    }


class Validator(object):
    """
    Class which handles creating or fetching validation results for File
    and FileUpload instances.

    It forwards the actual validation to `devhub.tasks:validate_upload`
    and `devhub.tasks:validate_file` but implements shortcuts for
    legacy add-ons and search plugins to avoid running the linter.
    """

    def __init__(self, file_, addon=None, listed=None, final_task=None):
        self.addon = addon
        self.file = None
        self.prev_file = None

        if isinstance(file_, FileUpload):
            assert listed is not None
            channel = (amo.RELEASE_CHANNEL_LISTED if listed else
                       amo.RELEASE_CHANNEL_UNLISTED)
            is_mozilla_signed = False

            # We're dealing with a bare file upload. Try to extract the
            # metadata that we need to match it against a previous upload
            # from the file itself.
            try:
                addon_data = parse_addon(file_, minimal=True)
                is_mozilla_signed = addon_data.get(
                    'is_mozilla_signed_extension', False)
            except ValidationError as form_error:
                log.info('could not parse addon for upload {}: {}'
                         .format(file_.pk, form_error))
                addon_data = None
            else:
                file_.update(version=addon_data.get('version'))

            assert not file_.validation

            tasks_in_parallel = [tasks.forward_linter_results.s(file_.pk)]

            if waffle.switch_is_active('enable-yara'):
                tasks_in_parallel.append(run_yara.s(file_.pk))

            if waffle.switch_is_active('enable-customs'):
                tasks_in_parallel.append(run_customs.s(file_.pk))

            if waffle.switch_is_active('enable-wat'):
                tasks_in_parallel.append(run_wat.s(file_.pk))

            validation_tasks = [
                tasks.create_initial_validation_results.si(),
                repack_fileupload.s(file_.pk),
                tasks.validate_upload.s(file_.pk, channel),
                tasks.check_for_api_keys_in_file.s(file_.pk),
                chord(tasks_in_parallel, call_ml_api.s(file_.pk)),
                tasks.handle_upload_validation_result.s(file_.pk,
                                                        channel,
                                                        is_mozilla_signed)
            ]
        elif isinstance(file_, File):
            # The listed flag for a File object should always come from
            # the status of its owner Addon. If the caller tries to override
            # this, something is wrong.
            assert listed is None

            channel = file_.version.channel
            is_mozilla_signed = file_.is_mozilla_signed_extension

            self.file = file_
            self.addon = self.file.version.addon
            addon_data = {'guid': self.addon.guid,
                          'version': self.file.version.version}

            validation_tasks = [
                tasks.create_initial_validation_results.si(),
                tasks.validate_file.s(file_.pk),
                tasks.handle_file_validation_result.s(file_.pk)
            ]
        else:
            raise ValueError

        if final_task:
            validation_tasks.append(final_task)

        self.task = chain(*validation_tasks)

        # Create a cache key for the task, so multiple requests to validate the
        # same object do not result in duplicate tasks.
        opts = file_._meta
        self.cache_key = 'validation-task:{0}.{1}:{2}:{3}'.format(
            opts.app_label, opts.object_name, file_.pk, listed)

    def get_task(self):
        """Return task chain to execute to trigger validation."""
        return self.task


def add_dynamic_theme_tag(version):
    if version.channel != amo.RELEASE_CHANNEL_LISTED:
        return
    files = version.all_files
    if any('theme' in file_.webext_permissions_list for file_ in files):
        Tag(tag_text='dynamic theme').save_tag(version.addon)


def extract_theme_properties(addon, channel):
    version = addon.find_latest_version(channel)
    if not version or not version.all_files:
        return {}
    try:
        parsed_data = parse_xpi(
            version.all_files[0].file_path, addon=addon, user=core.get_user())
    except ValidationError:
        # If we can't parse the existing manifest safely return.
        return {}
    theme_props = parsed_data.get('theme', {})
    # pre-process colors to deprecated colors; strip spaces.
    theme_props['colors'] = dict(
        process_color_value(prop, color)
        for prop, color in theme_props.get('colors', {}).items())
    # upgrade manifest from deprecated headerURL to theme_frame
    if 'headerURL' in theme_props.get('images', {}):
        url = theme_props['images'].pop('headerURL')
        theme_props['images']['theme_frame'] = url
    return theme_props


def wizard_unsupported_properties(data, wizard_fields):
    # collect any 'theme' level unsupported properties
    unsupported = [
        key for key in data.keys() if key not in ['colors', 'images']]
    # and any unsupported 'colors' properties
    unsupported += [
        key for key in data.get('colors', {}) if key not in wizard_fields]
    # and finally any 'images' properties (wizard only supports the background)
    unsupported += [
        key for key in data.get('images', {}) if key != 'theme_frame']

    return unsupported


class UploadRestrictionChecker:
    """
    Wrapper around all our submission restriction classes.

    To use, instantiate it with the request and call is_submission_allowed().
    After this method has been called, the error message to show the user if
    needed will be available through get_error_message()
    """
    # We use UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES because it
    # currently matches the order we want to check things. If that ever
    # changes, keep RESTRICTION_CLASSES_CHOICES current order (to keep existing
    # records intact) but change the `restriction_choices` definition below.
    restriction_choices = UserRestrictionHistory.RESTRICTION_CLASSES_CHOICES

    def __init__(self, request):
        self.request = request
        self.failed_restrictions = []

    def is_submission_allowed(self, check_dev_agreement=True):
        """
        Check whether the `request` passed is allowed to submit add-ons.
        Will check all classes declared in self.restriction_classes.

        Pass check_dev_agreement=False to avoid checking
        DeveloperAgreementRestriction class, which is useful only for the
        developer agreement page itself, where the developer hasn't validated
        the agreement yet but we want to do the other checks anyway.
        """
        if self.request.user and self.request.user.bypass_upload_restrictions:
            return True

        for restriction_number, cls in self.restriction_choices:
            if (check_dev_agreement is False and
                    cls == DeveloperAgreementRestriction):
                continue
            allowed = cls.allow_request(self.request)
            if not allowed:
                self.failed_restrictions.append(cls)
                statsd.incr(
                    'devhub.is_submission_allowed.%s.failure' % cls.__name__)
                if self.request.user and self.request.user.is_authenticated:
                    UserRestrictionHistory.objects.create(
                        user=self.request.user,
                        ip_address=self.request.META.get('REMOTE_ADDR', ''),
                        last_login_ip=self.request.user.last_login_ip or '',
                        restriction=restriction_number)
        suffix = 'success' if not self.failed_restrictions else 'failure'
        statsd.incr('devhub.is_submission_allowed.%s' % suffix)
        return not self.failed_restrictions

    def get_error_message(self):
        """
        Return the error message to show to the user after a call to
        is_submission_allowed_for_request() has been made. Will return the
        message to be displayed to the user, or None if there is no specific
        restriction applying.
        """
        try:
            msg = self.failed_restrictions[0].get_error_message(
                is_api=self.request.is_api)
        except IndexError:
            msg = None
        return msg


def fetch_existing_translations_from_addon(addon, properties):
    translation_ids_gen = (
        getattr(addon, prop + '_id', None) for prop in properties)
    translation_ids = [id_ for id_ in translation_ids_gen if id_]
    # Just get all the values together to make it simplier
    return {
        str(value)
        for value in Translation.objects.filter(id__in=translation_ids)}
