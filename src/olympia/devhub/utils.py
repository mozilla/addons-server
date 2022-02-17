import uuid

from django.conf import settings
from django.db import transaction
from django.forms import ValidationError
from django.utils.translation import gettext

import waffle

from celery import chain, chord
from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo, core
from olympia.amo.urlresolvers import linkify_and_clean
from olympia.files.models import File, FileUpload
from olympia.files.tasks import repack_fileupload
from olympia.files.utils import parse_addon, parse_xpi
from olympia.scanners.tasks import run_customs, run_wat, run_yara, call_mad_api
from olympia.translations.models import Translation
from olympia.versions.models import Version
from olympia.versions.utils import process_color_value

from . import tasks


log = olympia.core.logger.getLogger('z.devhub')


def process_validation(validation, file_hash=None, channel=amo.RELEASE_CHANNEL_LISTED):
    """Process validation results into the format expected by the web
    frontend, including transforming certain fields into HTML,  mangling
    compatibility messages, and limiting the number of messages displayed."""
    validation = fix_addons_linter_output(validation, channel=channel)

    # Set an ending tier if we don't have one (which probably means
    # we're dealing with mock validation results or the addons-linter).
    validation.setdefault('ending_tier', 0)

    if not validation['ending_tier'] and validation['messages']:
        validation['ending_tier'] = max(
            msg.get('tier', -1) for msg in validation['messages']
        )

    limit_validation_results(validation)

    htmlify_validation(validation)

    return validation


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

        compat_type = (
            msg_type if any(msg.get('compatibility_type') for msg in messages) else None
        )

        message = (
            gettext(
                'Validation generated too many errors/warnings so %s '
                'messages were truncated. After addressing the visible '
                "messages, you'll be able to see the others."
            )
            % leftover_count
        )

        messages.insert(
            0,
            {
                'tier': 1,
                'type': msg_type,
                # To respect the message structure, see bug 1139674.
                'id': ['validation', 'messages', 'truncated'],
                'message': message,
                'description': [],
                'compatibility_type': compat_type,
            },
        )


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
                linkify_and_clean(text) for text in msg['description']
            ]


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


class Validator:
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
            channel = (
                amo.RELEASE_CHANNEL_LISTED if listed else amo.RELEASE_CHANNEL_UNLISTED
            )
            is_mozilla_signed = False

            # We're dealing with a bare file upload. Try to extract the
            # metadata that we need to match it against a previous upload
            # from the file itself.
            try:
                addon_data = parse_addon(file_, minimal=True)
                is_mozilla_signed = addon_data.get('is_mozilla_signed_extension', False)
            except ValidationError as form_error:
                log.info(
                    'could not parse addon for upload {}: {}'.format(
                        file_.pk, form_error
                    )
                )
                addon_data = None
            else:
                file_.update(version=addon_data.get('version'))

            assert not file_.validation

            validation_tasks = self.create_file_upload_tasks(
                upload_pk=file_.pk, channel=channel, is_mozilla_signed=is_mozilla_signed
            )
        elif isinstance(file_, File):
            # The listed flag for a File object should always come from
            # the status of its owner Addon. If the caller tries to override
            # this, something is wrong.
            assert listed is None

            channel = file_.version.channel
            is_mozilla_signed = file_.is_mozilla_signed_extension

            self.file = file_
            self.addon = self.file.version.addon
            addon_data = {'guid': self.addon.guid, 'version': self.file.version.version}

            validation_tasks = [
                tasks.create_initial_validation_results.si(),
                tasks.validate_file.s(file_.pk),
                tasks.handle_file_validation_result.s(file_.pk),
            ]
        else:
            raise ValueError

        if final_task:
            validation_tasks.append(final_task)

        self.task = chain(*validation_tasks)

        # Create a cache key for the task, so multiple requests to validate the
        # same object do not result in duplicate tasks.
        opts = file_._meta
        self.cache_key = 'validation-task:{}.{}:{}:{}'.format(
            opts.app_label, opts.object_name, file_.pk, listed
        )

    def get_task(self):
        """Return task chain to execute to trigger validation."""
        return self.task

    def create_file_upload_tasks(self, upload_pk, channel, is_mozilla_signed):
        """
        This method creates the validation chain used during the submission
        process, combining tasks in parallel (chord) with tasks chained
        together (where the output is used as input of the next task).
        """
        tasks_in_parallel = [tasks.forward_linter_results.s(upload_pk)]

        if waffle.switch_is_active('enable-yara'):
            tasks_in_parallel.append(run_yara.s(upload_pk))

        if waffle.switch_is_active('enable-customs'):
            tasks_in_parallel.append(run_customs.s(upload_pk))

        if waffle.switch_is_active('enable-wat'):
            tasks_in_parallel.append(run_wat.s(upload_pk))

        return [
            tasks.create_initial_validation_results.si(),
            repack_fileupload.s(upload_pk),
            tasks.validate_upload.s(upload_pk, channel),
            tasks.check_for_api_keys_in_file.s(upload_pk),
            chord(tasks_in_parallel, call_mad_api.s(upload_pk)),
            tasks.handle_upload_validation_result.s(
                upload_pk, channel, is_mozilla_signed
            ),
        ]


def extract_theme_properties(addon, channel):
    version = addon.find_latest_version(channel)
    if not version:
        return {}
    try:
        parsed_data = parse_xpi(
            version.file.file_path, addon=addon, user=core.get_user()
        )
    except ValidationError:
        # If we can't parse the existing manifest safely return.
        return {}
    theme_props = parsed_data.get('theme', {})
    # pre-process colors to deprecated colors; strip spaces.
    theme_props['colors'] = dict(
        process_color_value(prop, color)
        for prop, color in theme_props.get('colors', {}).items()
    )
    # upgrade manifest from deprecated headerURL to theme_frame
    if 'headerURL' in theme_props.get('images', {}):
        url = theme_props['images'].pop('headerURL')
        theme_props['images']['theme_frame'] = url
    return theme_props


def wizard_unsupported_properties(data, wizard_fields):
    # collect any 'theme' level unsupported properties
    unsupported = [key for key in data.keys() if key not in ['colors', 'images']]
    # and any unsupported 'colors' properties
    unsupported += [key for key in data.get('colors', {}) if key not in wizard_fields]
    # and finally any 'images' properties (wizard only supports the background)
    unsupported += [key for key in data.get('images', {}) if key != 'theme_frame']

    return unsupported


def fetch_existing_translations_from_addon(addon, properties):
    translation_ids_gen = (getattr(addon, prop + '_id', None) for prop in properties)
    translation_ids = [id_ for id_ in translation_ids_gen if id_]
    # Just get all the values together to make it simplier
    return {str(value) for value in Translation.objects.filter(id__in=translation_ids)}


def add_manifest_version_error(validation):
    mv = validation.get('metadata', {}).get('manifestVersion')
    if (
        mv != 3
        or waffle.switch_is_active('enable-mv3-submissions')
        or 'messages' not in validation
    ):
        return
    msg = gettext(
        'Manifest V3 is currently not supported for upload. '
        '{start_href}Read more about the support timeline{end_href}.'
    )
    url = 'https://blog.mozilla.org/addons/2021/05/27/manifest-v3-update/'
    start_href = f'<a href="{url}" target="_blank" rel="noopener">'

    new_error_message = msg.format(start_href=start_href, end_href='</a>')
    for index, message in enumerate(validation['messages']):
        if message.get('dataPath') == '/manifest_version':
            # if we find the linter manifest_version=3 warning, replace it
            validation['messages'][index]['message'] = new_error_message
            break
    else:
        # otherwise insert a new error at the start of the errors
        validation['messages'].insert(
            0,
            {
                'type': 'error',
                'message': new_error_message,
                'tier': 1,
                'fatal': True,
            },
        )


@transaction.atomic
def create_version_for_upload(addon, upload, channel, parsed_data=None):
    fileupload_exists = addon.fileupload_set.filter(
        created__gt=upload.created, version=upload.version
    ).exists()
    version_exists = Version.unfiltered.filter(
        addon=addon, version=upload.version
    ).exists()
    if fileupload_exists or version_exists:
        log.info(
            'Skipping Version creation for {upload_uuid} that would '
            ' cause duplicate version'.format(upload_uuid=upload.uuid)
        )
        return None
    else:
        log.info(
            'Creating version for {upload_uuid} that passed '
            'validation'.format(upload_uuid=upload.uuid)
        )
        # Note: if we somehow managed to get here with an invalid add-on,
        # parse_addon() will raise ValidationError and the task will fail
        # loudly in sentry.
        if parsed_data is None:
            parsed_data = parse_addon(upload, addon, user=upload.user)
        new_addon = not Version.unfiltered.filter(addon=addon).exists()
        version = Version.from_upload(
            upload,
            addon,
            channel,
            selected_apps=[x[0] for x in amo.APPS_CHOICES],
            parsed_data=parsed_data,
        )
        channel_name = amo.CHANNEL_CHOICES_API[channel]
        # This function is only called via the signing api flow
        statsd.incr(
            f'signing.submission.{"addon" if new_addon else "version"}.{channel_name}'
        )
        # The add-on's status will be STATUS_NULL when its first version is
        # created because the version has no files when it gets added and it
        # gets flagged as invalid. We need to manually set the status.
        if addon.status == amo.STATUS_NULL and channel == amo.RELEASE_CHANNEL_LISTED:
            addon.update(status=amo.STATUS_NOMINATED)
        return version
