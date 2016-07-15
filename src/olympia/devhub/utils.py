import uuid
import json
from json.decoder import JSONArray

from django.conf import settings
from django.db.models import Q
from django.forms import ValidationError
from django.utils.translation import ugettext as _

from celery import chain, group
from validator.constants import SIGNING_SEVERITIES
from validator.version import Version
import commonware.log

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.decorators import write
from olympia.amo.urlresolvers import linkify_escape
from olympia.files.models import File, FileUpload, ValidationAnnotation
from olympia.files.utils import parse_addon

from . import tasks

log = commonware.log.getLogger('z.devhub')


def process_validation(validation, is_compatibility=False, file_hash=None):
    """Process validation results into the format expected by the web
    frontend, including transforming certain fields into HTML,  mangling
    compatibility messages, and limiting the number of messages displayed."""
    validation = fix_addons_linter_output(validation)

    if is_compatibility:
        mangle_compatibility_messages(validation)

    # Set an ending tier if we don't have one (which probably means
    # we're dealing with mock validation results or the addons-linter).
    validation.setdefault('ending_tier', 0)

    if not validation['ending_tier'] and validation['messages']:
        validation['ending_tier'] = max(msg.get('tier', -1)
                                        for msg in validation['messages'])

    if file_hash:
        ValidationComparator(validation).annotate_results(file_hash)

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
            if message.get('signing_severity'):
                return 1
            else:
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

        messages.insert(0, {
            'tier': 1,
            'type': msg_type,
            # To respect the message structure, see bug 1139674.
            'id': ['validation', 'messages', 'truncated'],
            'message': _('Validation generated too many errors/'
                         'warnings so %s messages were truncated. '
                         'After addressing the visible messages, '
                         "you'll be able to see the others.") % leftover_count,
            'description': [],
            'compatibility_type': compat_type})


def htmlify_validation(validation):
    """Process the `message`, `description`, and `signing_help` fields into
    safe HTML, with URLs turned into links."""

    for msg in validation['messages']:
        msg['message'] = linkify_escape(msg['message'])

        for key in 'description', 'signing_help':
            if key in msg:
                # These may be returned as single strings, or lists of
                # strings. Turn them all into lists for simplicity
                # on the client side.
                if not isinstance(msg[key], (list, tuple)):
                    msg[key] = [msg[key]]

                msg[key] = [linkify_escape(text) for text in msg[key]]


def fix_addons_linter_output(validation, listed=True):
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
        'metadata': {
            'listed': listed,
            'identified_files': identified_files,
            'processed_by_addons_linter': True,
        },
        'signing_summary': {
            'low': 0,
            'medium': 0,
            'high': 0,
            'trivial': 0
        },
        # The addons-linter only deals with WebExtensions and no longer
        # outputs this itself, so we hardcode it.
        'detected_type': 'extension',
        'ending_tier': 5,
    }


class ValidationAnnotator(object):
    """Class which handles creating or fetching validation results for File
    and FileUpload instances, and annotating them based on information not
    available to the validator. This includes finding previously approved
    versions and comparing newer results with those."""

    def __init__(self, file_, addon=None, listed=None):
        self.addon = addon
        self.file = None
        self.prev_file = None

        if isinstance(file_, FileUpload):
            save = tasks.handle_upload_validation_result
            is_webextension = False
            # We're dealing with a bare file upload. Try to extract the
            # metadata that we need to match it against a previous upload
            # from the file itself.
            try:
                addon_data = parse_addon(file_, check=False)
                is_webextension = addon_data.get('is_webextension', False)
            except ValidationError as form_error:
                log.info('could not parse addon for upload {}: {}'
                         .format(file_.pk, form_error))
                addon_data = None
            else:
                file_.update(version=addon_data.get('version'))

            validate = self.validate_upload(file_, listed, is_webextension)
        elif isinstance(file_, File):
            # The listed flag for a File object should always come from
            # the status of its owner Addon. If the caller tries to override
            # this, something is wrong.
            assert listed is None

            save = tasks.handle_file_validation_result
            validate = self.validate_file(file_)

            self.file = file_
            self.addon = self.file.version.addon
            addon_data = {'guid': self.addon.guid,
                          'version': self.file.version.version}
        else:
            raise ValueError

        if addon_data and addon_data['guid']:
            # If we have a valid file, try to find an associated Addon
            # object, and a valid former submission to compare against.
            try:
                self.addon = (self.addon or
                              Addon.with_unlisted.get(guid=addon_data['guid']))
            except Addon.DoesNotExist:
                pass

            self.prev_file = self.find_previous_version(addon_data['version'])
            if self.prev_file:
                # Group both tasks so the results can be merged when
                # the jobs complete.
                validate = group((validate,
                                  self.validate_file(self.prev_file)))

        # Fallback error handler to save a set of exception results, in case
        # anything unexpected happens during processing.
        on_error = save.subtask([amo.VALIDATOR_SKELETON_EXCEPTION, file_.pk],
                                {'annotate': False}, immutable=True)

        # When the validation jobs complete, pass the results to the
        # appropriate annotate/save task for the object type.
        self.task = chain(validate, save.subtask([file_.pk],
                                                 link_error=on_error))

        # Create a cache key for the task, so multiple requests to
        # validate the same object do not result in duplicate tasks.
        opts = file_._meta
        self.cache_key = 'validation-task:{0}.{1}:{2}:{3}'.format(
            opts.app_label, opts.object_name, file_.pk, listed)

    @write
    def update_annotations(self):
        """Update the annotations for our file with the annotations for any
        previous matching file, if it exists."""

        if not (self.file and self.prev_file):
            # We don't have two Files to work with. Nothing to do.
            return

        hash_ = self.file.original_hash
        if ValidationAnnotation.objects.filter(file_hash=hash_).exists():
            # We already have annotations for this file hash.
            # Don't add any more.
            return

        comparator = ValidationComparator(
            json.loads(self.file.validation.validation))

        keys = [json.dumps(key) for key in comparator.messages.iterkeys()]

        annos = ValidationAnnotation.objects.filter(
            file_hash=self.prev_file.original_hash, message_key__in=keys)

        ValidationAnnotation.objects.bulk_create(
            ValidationAnnotation(file_hash=hash_, message_key=anno.message_key,
                                 ignore_duplicates=anno.ignore_duplicates)
            for anno in annos)

    @staticmethod
    def validate_file(file):
        """Return a subtask to validate a File instance."""
        kwargs = {
            'hash_': file.original_hash,
            'is_webextension': file.is_webextension}
        return tasks.validate_file.subtask([file.pk], kwargs)

    @staticmethod
    def validate_upload(upload, is_listed, is_webextension):
        """Return a subtask to validate a FileUpload instance."""
        assert not upload.validation

        kwargs = {
            'hash_': upload.hash,
            'listed': is_listed,
            'is_webextension': is_webextension}
        return tasks.validate_file_path.subtask([upload.path], kwargs)

    def find_previous_version(self, version):
        """Find the most recent previous version of this add-on, prior to
        `version`, that we can use to compare validation results."""

        if not self.addon:
            return

        version = Version(version)
        statuses = (amo.STATUS_PUBLIC, amo.STATUS_LITE)

        # Find any previous version of this add-on with the correct status
        # to match the given file.
        files = File.objects.filter(version__addon=self.addon)

        if self.addon.is_listed and (self.file and
                                     self.file.status != amo.STATUS_BETA):
            # TODO: We'll also need to implement this for FileUploads
            # when we can accurately determine whether a new upload
            # is a beta version.
            if self.addon.status in (amo.STATUS_PUBLIC, amo.STATUS_NOMINATED,
                                     amo.STATUS_LITE_AND_NOMINATED):
                files = files.filter(status=amo.STATUS_PUBLIC)
            else:
                files = files.filter(status__in=statuses)
        else:
            files = files.filter(Q(status__in=statuses) |
                                 Q(status=amo.STATUS_BETA, is_signed=True))

        if self.file:

            # Add some extra filters if we're validating a File instance,
            # to try to get the closest possible match.
            files = (files.exclude(pk=self.file.pk)
                     # Files which are not for the same platform, but have
                     # other files in the same version which are.
                     .exclude(~Q(platform=self.file.platform) &
                              Q(version__files__platform=self.file.platform))
                     # Files which are not for either the same platform or for
                     # all platforms, but have other versions in the same
                     # version which are.
                     .exclude(~Q(platform__in=(self.file.platform,
                                               amo.PLATFORM_ALL.id)) &
                              Q(version__files__platform=amo.PLATFORM_ALL.id)))

        for file_ in files.order_by('-id'):
            # Only accept versions which come before the one we're validating.
            if Version(file_.version.version) < version:
                return file_


def JSONTuple(*args, **kw):
    """Parse a JSON array, and return it in tuple form, along with the
    character position where we stopped parsing. Simple wrapper around
    the stock JSONArray parser."""
    values, end = JSONArray(*args, **kw)
    return tuple(values), end


class HashableJSONDecoder(json.JSONDecoder):
    """A JSON decoder which deserializes arrays as tuples rather than lists."""
    def __init__(self, *args, **kwargs):
        super(HashableJSONDecoder, self).__init__()
        self.parse_array = JSONTuple
        self.scan_once = json.scanner.py_make_scanner(self)

json_decode = HashableJSONDecoder().decode


class ValidationComparator(object):
    """Compares the validation results from an older version with a version
    currently being checked, and annotates results based on which messages
    may be ignored for the purposes of automated signing."""

    def __init__(self, validation):
        self.validation = validation

        self.messages = {self.message_key(msg): msg
                         for msg in validation['messages']}
        if None in self.messages:
            # `message_key` returns None for messages we can't compare.
            # They should all wind up in a single bucket in the messages dict,
            # so delete that item if it exists.
            del self.messages[None]

    @staticmethod
    def message_key(message):
        """Returns a hashable key for a message based on properties
        required when searching for a match."""

        # No context, message is not matchable.
        if not message.get('context'):
            return None

        def file_key(filename):
            """Return a hashable key for a message's filename, which may be
            a string, tuple, or list by default."""

            return (u'/'.join(filename) if isinstance(filename, (list, tuple))
                    else filename)

        # We need all of these values to be iterable, which means tuples
        # anywhere we might otherwise use lists. This includes any tuple
        # values emitted by the validator (since `json.loads` turns them into
        # lists), the return value of `.items()`, and so forth.
        return (tuple(message['id']),
                tuple(message['context']),
                file_key(message['file']),
                message.get('signing_severity'),
                ('context_data' in message and
                 tuple(sorted(message['context_data'].items()))))

    @staticmethod
    def match_messages(message1, message2):
        """Returns true if the two given messages match. The two messages
        are assumed to have identical `message_key` values."""

        # We'll eventually want to make this matching stricter, in particular
        # matching line numbers with some sort of slop factor.
        # For now, though, we just rely on the basic heuristic of file name
        # and context data extracted by `message_key`.
        return True

    def find_matching_message(self, message):
        """Finds a matching message in the saved validation results,
        based on the return value of `message_key` and `match_messages`,
        and return it. If no matching message exists, return None."""

        msg = self.messages.get(self.message_key(message))
        if msg and self.match_messages(msg, message):
            return msg

    @staticmethod
    def is_ignorable(message):
        """Returns true if a message may be ignored when a matching method
        appears in past results."""

        # The `ignore_duplicates` flag will be set by editors, to overrule
        # the basic signing severity heuristic. If it's present, it takes
        # precedence.
        low_severity = (message.get('type') != 'error' and
                        message.get('signing_severity') in ('trivial', 'low'))
        return message.get('ignore_duplicates', low_severity)

    def compare_results(self, validation):
        """Compare the saved validation results with a newer set, and annotate
        the newer set as appropriate.

        Any results in `validation` which match a result in the older set
        will be annotated with a 'matched' key, containing a copy of the
        message from the previous results.

        Any results which both match a previous message and which can as a
        result be ignored will be annotated with an 'ignored' key, with a value
        of `True`.

        The 'signing_summary' dict will be replaced with a new dict containing
        counts of non-ignored messages. An 'ignored_signing_summary' dict
        will be added, containing counts only of ignored messages."""

        signing_summary = {level: 0 for level in SIGNING_SEVERITIES}
        ignored_summary = {level: 0 for level in SIGNING_SEVERITIES}

        for msg in validation['messages']:
            severity = msg.get('signing_severity')
            prev_msg = self.find_matching_message(msg)
            if prev_msg:
                msg['matched'] = prev_msg.copy()
                if 'matched' in msg['matched']:
                    del msg['matched']['matched']
                if severity:
                    msg['ignored'] = self.is_ignorable(prev_msg)

            if severity:
                if 'ignore_duplicates' not in msg and self.message_key(msg):
                    msg['ignore_duplicates'] = self.is_ignorable(msg)
                if msg.get('ignored'):
                    ignored_summary[severity] += 1
                else:
                    signing_summary[severity] += 1

        validation['signing_summary'] = signing_summary
        validation['signing_ignored_summary'] = ignored_summary
        return validation

    def annotate_results(self, file_hash):
        """Annotate our `validation` result set with any stored annotations
        for a file with `file_hash`."""

        annotations = (ValidationAnnotation.objects
                       .filter(file_hash=file_hash,
                               ignore_duplicates__isnull=False)
                       .values_list('message_key', 'ignore_duplicates'))

        for message_key, ignore_duplicates in annotations:
            key = json_decode(message_key)
            msg = self.messages.get(key)
            if msg:
                msg['ignore_duplicates'] = ignore_duplicates

        for msg in self.messages.itervalues():
            if 'ignore_duplicates' not in msg and 'signing_severity' in msg:
                msg['ignore_duplicates'] = self.is_ignorable(msg)
