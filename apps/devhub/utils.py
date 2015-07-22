from django.conf import settings
from django.db.models import Q
from django.forms import ValidationError

from celery import chain, group
from tower import ugettext as _

import amo
from addons.models import Addon
from amo.utils import escape_all
from files.models import File, FileUpload
from files.utils import parse_addon
from validator.version import Version
from . import tasks


# FIXME: Move to `validator.constants`.
SEVERITIES = {'trivial', 'low', 'medium', 'high'}


def make_validation_results(data, is_compatibility=False):
    if data['validation']:
        data['validation'] = limit_validation_results(escape_validation(
            data['validation']))
    data['error'] = hide_traceback(data['error'])
    return data


def hide_traceback(error):
    """Safe wrapper around JSON dict containing a validation result.
    """
    if not settings.EXPOSE_VALIDATOR_TRACEBACKS and error:
        # Just expose the message, not the traceback
        return error.strip().split('\n')[-1].strip()
    else:
        return error


def limit_validation_results(validation, is_compatibility=False):
    lim = settings.VALIDATOR_MESSAGE_LIMIT
    if lim:
        del validation['messages'][lim:]
        if validation.get('compatibility_summary'):
            cs = validation['compatibility_summary']
            compatibility_count = (
                cs['errors'] + cs['warnings'] + cs['notices'])
        else:
            cs = {}
            compatibility_count = 0
        leftover_count = (validation.get('errors', 0)
                          + validation.get('warnings', 0)
                          + validation.get('notices', 0)
                          + compatibility_count
                          - lim)
        if leftover_count > 0:
            msgtype = 'notice'
            if is_compatibility:
                if cs.get('errors'):
                    msgtype = 'error'
                elif cs.get('warnings'):
                    msgtype = 'warning'
            else:
                if validation['errors']:
                    msgtype = 'error'
                elif validation['warnings']:
                    msgtype = 'warning'
            validation['messages'].append({
                'tier': 1,
                'type': msgtype,
                # To respect the message structure, see bug 1139674.
                'id': ['validation', 'messages', 'truncated'],
                'message': (_('Validation generated too many errors/'
                              'warnings so %s messages were truncated. '
                              'After addressing the visible messages, '
                              "you'll be able to see the others.")
                            % (leftover_count,)),
                'compatibility_type': None})
    if is_compatibility:
        compat = validation['compatibility_summary']
        for k in ('errors', 'warnings', 'notices'):
            validation[k] = compat[k]
        for msg in validation['messages']:
            if msg['compatibility_type']:
                msg['type'] = msg['compatibility_type']
    return validation


def escape_validation(validation):
    ending_tier = validation.get('ending_tier', 0)
    for msg in validation.get('messages', []):
        tier = msg.get('tier', -1)  # Use -1 so we know it isn't 0.
        if tier > ending_tier:
            ending_tier = tier
        if tier == 0:
            # We can't display a message if it's on tier 0.
            # Should get fixed soon in bug 617481
            msg['tier'] = 1
    validation['ending_tier'] = ending_tier
    return escape_all(validation, linkify_only_full=True)


class ValidationAnnotator(object):
    """Class which handles creating or fetching validation results for File
    and FileUpload instances, and annotating them based on information not
    available to the validator. This includes finding previously approved
    versions and comparing newer results with those."""

    def __init__(self, file_, addon=None, listed=None):
        self.addon = addon
        self.file = None

        if isinstance(file_, FileUpload):
            save = tasks.handle_upload_validation_result
            validate = self.validate_upload(file_, listed)

            # We're dealing with a bare file upload. Try to extract the
            # metadata that we need to match it against a previous upload
            # from the file itself.
            try:
                addon_data = parse_addon(file_, check=False)
            except ValidationError:
                addon_data = None
        elif isinstance(file_, File):
            # The listed flag for a File object should always come from
            # the status of its owner Addon. If the caller tries to override
            # this, something is wrong.
            assert listed is None

            save = tasks.handle_file_validation_result
            validate = self.validate_file(file_)

            self.file = file_
            self.addon = self.file.version.addon
            addon_data = {'guid': self.addon.id,
                          'version': self.file.version.version}
        else:
            raise ValueError

        if addon_data:
            # If we have a valid file, try to find an associated Addon
            # object, and a valid former submission to compare against.
            try:
                self.addon = (self.addon or
                              Addon.with_unlisted.get(guid=addon_data['guid']))
            except Addon.DoesNotExist:
                pass

            prev_file = self.find_previous_version(addon_data['version'])
            if prev_file:
                # Group both tasks so the results can be merged when
                # the jobs complete.
                validate = group((validate, self.validate_file(prev_file)))

        # When the validation jobs complete, pass the results to the
        # appropriate annotate/save task for the object type.
        self.task = chain(validate, save.subtask([file_.pk]))

    @staticmethod
    def validate_file(file):
        """Return a subtask to validate a File instance."""
        return tasks.validate_file.subtask([file.pk])

    @staticmethod
    def validate_upload(upload, is_listed):
        """Return a subtask to validate a FileUpload instance."""
        assert not upload.validation

        return tasks.validate_upload.subtask([upload.pk, is_listed])

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


class ValidationComparator(object):
    """Compares the validation results from an older version with a version
    currently being checked, and annotates results based on which messages
    may be ignored for the purposes of automated signing."""

    def __init__(self, validation):
        self.validation = validation

        self.messages = {self.message_key(msg): msg
                         for msg in validation['messages']
                         if 'context' in msg}

    @staticmethod
    def message_key(message):
        """Returns a hashable key for a message based on properties
        required when searching for a match."""

        # No context, message is not matchable.
        if 'context' not in message:
            return None

        # We need all of these values to be iterable, which means tuples
        # anywhere we might otherwise use lists. This includes any tuple
        # values emitted by the validator (since `json.loads` turns them into
        # lists), the return value of `.items()`, and so forth.
        return (tuple(message['id']),
                tuple(message['context']),
                message['file'],
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
        low_severity = message['signing_severity'] in ('trivial', 'low')
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

        signing_summary = {level: 0 for level in SEVERITIES}
        ignored_summary = {level: 0 for level in SEVERITIES}

        for msg in validation['messages']:
            severity = msg.get('signing_severity')
            prev_msg = self.find_matching_message(msg)
            if prev_msg:
                msg['matched'] = prev_msg
                if severity:
                    msg['ignored'] = self.is_ignorable(prev_msg)

            if severity:
                if msg.get('ignored'):
                    ignored_summary[severity] += 1
                else:
                    signing_summary[severity] += 1

        validation['signing_summary'] = signing_summary
        validation['signing_ignored_summary'] = ignored_summary
        return validation
