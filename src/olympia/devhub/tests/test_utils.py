import json
import os.path
from copy import deepcopy

import mock

from celery.result import AsyncResult
from django.conf import settings
from django.test.utils import override_settings

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.amo.tests import addon_factory, version_factory
from olympia.devhub import tasks, utils
from olympia.devhub.tasks import annotate_validation_results
from olympia.files.models import (
    File, FileUpload, FileValidation, ValidationAnnotation)
from olympia.versions.models import Version


def merge_dicts(base, changes):
    res = base.copy()
    res.update(changes)
    return res


class TestValidationComparator(TestCase):
    SIGNING_SUMMARY = {'high': 0, 'medium': 0, 'low': 0, 'trivial': 0}

    def setUp(self):
        super(TestValidationComparator, self).setUp()

        self.old_msg = {}
        self.new_msg = {}
        self.expected_msg = {}

    def compare(self, old, changes, expected_changes):
        """Compare two messages, and assert that the expected annotations are
        present.

        `old` is a message dict from the previous set of results,
        `new` is a dict containing the set of property changes between
        the old message and the new one, and `expected` is the full set of
        annotations expected to be added to the new message."""

        # Clear and update the original dicts so they can be referenced
        # in the structures passed as arguments.
        for msg in self.old_msg, self.new_msg, self.expected_msg:
            msg.clear()

        self.old_msg.update(old)
        self.new_msg.update(merge_dicts(old, changes))
        if expected_changes is not None:
            self.expected_msg.update(
                merge_dicts(self.new_msg, expected_changes))

        if ('signing_severity' in self.expected_msg and
                'ignore_duplicates' not in self.expected_msg):
            # The annotator should add an ignore_duplicates key to all
            # signing-related messages that don't have one.
            if utils.ValidationComparator.message_key(self.expected_msg):
                self.expected_msg['ignore_duplicates'] = (
                    utils.ValidationComparator.is_ignorable(self.expected_msg))

        results = self.run_comparator(self.old_msg, self.new_msg.copy())

        if expected_changes is not None:
            assert results['messages'] == [self.expected_msg]

        if 'signing_severity' in self.new_msg:
            summary = merge_dicts(self.SIGNING_SUMMARY,
                                  {self.new_msg['signing_severity']: 1})

            summaries = (results['signing_summary'],
                         results['signing_ignored_summary'])

            # If the message is ignored, we should see it counted only in the
            # ignored message summary, otherwise we should expect to see it
            # counted only in the main summary.
            if self.expected_msg.get('ignored'):
                assert summaries == (self.SIGNING_SUMMARY, summary)
            else:
                assert summaries == (summary, self.SIGNING_SUMMARY)

        return results

    def run_comparator(self, old, new):
        return (utils.ValidationComparator({'messages': [old]})
                .compare_results({'messages': [new]}))

    def test_compare_data(self):
        """Test that the `compare` merges data as expected."""

        A = {'id': ('a', 'b', 'c'),
             'file': 'thing.js',
             'context': ('x', 'y', 'z'),
             'thing': 'stuff'}

        B = {'thing': 'other_thing',
             'foo': 'bar'}

        C = {'matched': A}

        A_plus_B = {'id': ('a', 'b', 'c'),
                    'file': 'thing.js',
                    'context': ('x', 'y', 'z'),
                    'thing': 'other_thing',
                    'foo': 'bar'}

        FINAL = {'id': ('a', 'b', 'c'),
                 'file': 'thing.js',
                 'context': ('x', 'y', 'z'),
                 'thing': 'other_thing',
                 'foo': 'bar',
                 'matched': A}

        self.compare(A, B, C)

        assert self.old_msg == A
        assert self.new_msg == A_plus_B
        assert self.expected_msg == FINAL

        self.compare(A, B, {'matched': self.old_msg})

        assert self.old_msg == A
        assert self.new_msg == A_plus_B
        assert self.expected_msg == FINAL

    def test_compare_nested_matches(self):
        """Test that nested matches are not included."""

        old = {
            'id': ('a', 'b', 'c'),
            'file': 'thing.js',
            'context': ('x', 'y', 'z'),
            'thing': 'stuff',
            'matched': {'something': 'else'},
        }
        old_without_matched = old.copy()
        del old_without_matched['matched']

        changes = {
            'thing': 'other_thing',
            'foo': 'bar',
        }

        expected_result = {
            'id': ('a', 'b', 'c'),
            'file': 'thing.js',
            'context': ('x', 'y', 'z'),
            'thing': 'other_thing',
            'foo': 'bar',
            'matched': old_without_matched,
        }

        results = self.compare(old, changes, expected_changes=None)
        assert results['messages'] == [expected_result]

    def test_compare_results(self):
        """Test that `compare` tests results correctly."""

        with mock.patch.object(self, 'run_comparator') as comparator:
            MSG = {'id': (), 'context': (), 'file': 'file.js',
                   'signing_severity': 'low'}
            EXPECTED = {'matched': MSG, 'ignored': True}
            FINAL = merge_dicts(MSG, EXPECTED)

            comparator.return_value = {
                'messages': [FINAL],
                'signing_summary': {'low': 0, 'medium': 0, 'high': 0,
                                    'trivial': 0},
                'signing_ignored_summary': {'low': 1, 'medium': 0, 'high': 0,
                                            'trivial': 0}}

            # Signing summary with ignored messages:
            self.compare(MSG, {}, EXPECTED)

            comparator.return_value['signing_summary']['low'] = 1
            try:
                self.compare(MSG, {}, EXPECTED)
            except AssertionError:
                pass
            else:
                assert False, 'Bad signing summary passed.'

            comparator.return_value['signing_summary']['low'] = 0
            comparator.return_value['signing_ignored_summary']['low'] = 0
            try:
                self.compare(MSG, {}, EXPECTED)
            except AssertionError:
                pass
            else:
                assert False, 'Bad ignored signing summary passed.'

            # Signing summary without ignored messages:
            CHANGES = {'id': ('a', 'b', 'c')}
            FINAL = merge_dicts(MSG, CHANGES)

            comparator.return_value['messages'] = [FINAL]
            comparator.return_value['signing_summary']['low'] = 1

            self.compare(MSG, CHANGES, {})

            comparator.return_value['signing_summary']['low'] = 0
            try:
                self.compare(MSG, CHANGES, {})
            except AssertionError:
                pass
            else:
                assert False, 'Bad signing summary passed.'

            comparator.return_value['signing_summary']['low'] = 1
            comparator.return_value['signing_ignored_summary']['low'] = 1
            try:
                self.compare(MSG, CHANGES, {})
            except AssertionError:
                pass
            else:
                assert False, 'Bad ignored signing summary passed.'

    def test_matching_message(self):
        """Test the behavior of matching messages."""

        # Low severity messages are ignored unless flagged as not ignorable.
        for severity in 'low', 'trivial':
            self.compare({'id': ('a', 'b', 'c'),
                          'signing_severity': severity,
                          'context': ('x', 'y', 'z'),
                          'file': 'foo.js'},
                         {},
                         {'ignored': True,
                          'matched': self.old_msg})

            self.compare({'id': ('a', 'b', 'c'),
                          'signing_severity': severity,
                          'ignore_duplicates': False,
                          'context': ('x', 'y', 'z'),
                          'file': 'foo.js'},
                         {},
                         {'ignored': False,
                          'matched': self.old_msg})

        # Other severities are ignored only when flagged as ignorable.
        for severity in 'medium', 'high':
            self.compare({'id': ('a', 'b', 'c'),
                          'signing_severity': severity,
                          'context': ('x', 'y', 'z'),
                          'file': 'foo.js'},
                         {},
                         {'ignored': False,
                          'matched': self.old_msg})

            self.compare({'id': ('a', 'b', 'c'),
                          'signing_severity': severity,
                          'ignore_duplicates': True,
                          'context': ('x', 'y', 'z'),
                          'file': 'foo.js'},
                         {},
                         {'ignored': True,
                          'matched': self.old_msg})

        # Check that unchecked properties don't matter.
        self.compare({'id': ('a', 'b', 'c'),
                      'signing_severity': 'low',
                      'context': ('x', 'y', 'z'),
                      'file': 'foo.js'},
                     {'thing': 'stuff'},
                     {'ignored': True,
                      'matched': self.old_msg})

        # Non-signing messages should be matched, but not annotated for
        # ignorability.
        self.compare({'id': ('a', 'b', 'c'),
                      'context': ('x', 'y', 'z'),
                      'file': 'foo.js'},
                     {},
                     {'matched': self.old_msg})

    def test_non_matching_messages(self):
        """Test that messages which should not match, don't."""

        message = {'id': ('a', 'b', 'c'),
                   'signing_severity': 'low',
                   'context': ('x', 'y', 'z'),
                   'context_data': {'function': 'foo_bar'},
                   'file': 'foo.js'}

        self.compare(message, {'id': ('d', 'e', 'f')}, {})
        self.compare(message, {'signing_severity': 'high'}, {})
        self.compare(message, {'context': ('a', 'b', 'c')}, {})
        self.compare(message, {'context_data': {}}, {})
        self.compare(message, {'file': 'these-are-not-the-droids.js'}, {})

        # No context in the old message.
        msg = merge_dicts(message, {'context': None})
        self.compare(msg, {'context': ('a', 'b', 'c')}, {})
        self.compare(msg, {'context': None}, {})
        del msg['context']
        self.compare(msg, {'context': ('a', 'b', 'c')}, {})
        self.compare(msg, {'context': None}, {})

        # No signing severity in the old message.
        msg = merge_dicts(message, {'signing_severity': None})
        self.compare(msg, {'signing_severity': 'low'}, {})
        del msg['signing_severity']
        self.compare(msg, {'signing_severity': 'low'}, {})

        # Token non-signing message.
        self.compare({'id': ('a', 'b', 'c'),
                      'context': ('x', 'y', 'z'),
                      'file': 'foo.js'},
                     {'id': ()}, {})

    def test_file_tuples(self):
        """Test that messages with file tuples, rather than strings, are
        treated correctly."""

        file_tuple = (u'thing.jar', u'foo.js')
        file_list = list(file_tuple)
        file_string = u'/'.join(file_tuple)

        message = {'id': ('a', 'b', 'c'),
                   'signing_severity': 'low',
                   'context': ('x', 'y', 'z'),
                   'context_data': {'function': 'foo_bar'},
                   'file': file_tuple}

        matches = {'ignored': True, 'matched': self.old_msg}

        # Tuple, no changes, matches.
        self.compare(message, {}, matches)
        self.compare(message, {'file': file_list}, matches)
        self.compare(message, {'file': file_string}, matches)
        # Changes, fails.
        self.compare(message, {'file': 'foo thing.js'}, {})

        # List, no changes, matches.
        message['file'] = file_list
        self.compare(message, {}, matches)
        self.compare(message, {'file': file_list}, matches)
        self.compare(message, {'file': file_string}, matches)
        # Changes, fails.
        self.compare(message, {'file': 'foo thing.js'}, {})

        # String, no changes, matches.
        message['file'] = file_string
        self.compare(message, {}, matches)
        self.compare(message, {'file': file_list}, matches)
        self.compare(message, {'file': file_string}, matches)
        # Changes, fails.
        self.compare(message, {'file': 'foo thing.js'}, {})

    def test_json_deserialization(self):
        """Test that the JSON deserializer returns the expected hashable
        objects."""
        assert (utils.json_decode('["foo", ["bar", "baz"], 12, null, '
                                  '[], false]') ==
                ('foo', ('bar', 'baz'), 12, None, (), False))

    def test_annotate_results(self):
        """Test that results are annotated as expected."""

        RESULTS = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
        RESULTS['messages'] = [
            {'id': ['foo', 'bar'],
             'context': ['foo', 'bar', 'baz'],
             'file': 'foo',
             'signing_severity': 'low'},

            {'id': ['a', 'b'],
             'context': ['c', 'd', 'e'],
             'file': 'f',
             'ignore_duplicates': False,
             'signing_severity': 'high'},

            {'id': ['z', 'y'],
             'context': ['x', 'w', 'v'],
             'file': 'u',
             'signing_severity': 'high'},
        ]

        HASH = 'xxx'

        def annotation(hash_, message, **kw):
            """Create a ValidationAnnotation object for the given file hash,
            and the key of the given message, with the given keywords."""

            key = utils.ValidationComparator.message_key(message)
            return ValidationAnnotation(
                file_hash=hash_, message_key=json.dumps(key), **kw)

        # Create two annotations for this file, and one for a message in this
        # file, but with the wrong hash.
        ValidationAnnotation.objects.bulk_create((
            annotation(HASH, RESULTS['messages'][0], ignore_duplicates=False),
            annotation(HASH, RESULTS['messages'][1], ignore_duplicates=True),
            annotation('zzz', RESULTS['messages'][2], ignore_duplicates=True),
        ))

        # Annote a copy of the results.
        annotated = deepcopy(RESULTS)
        utils.ValidationComparator(annotated).annotate_results(HASH)

        # The two annotations for this file should be applied.
        assert annotated['messages'][0]['ignore_duplicates'] is False
        assert annotated['messages'][1]['ignore_duplicates'] is True
        # The annotation for the wrong file should not be applied, and
        # `ignore_duplicates` should be set to the default for the messge
        # severity (false).
        assert annotated['messages'][2]['ignore_duplicates'] is False

    def test_is_ignorable(self):
        """Test that is_ignorable returns the correct value in all relevant
        circumstances."""

        MESSAGE = {'id': ['foo', 'bar', 'baz'],
                   'message': 'Foo',
                   'description': 'Foo',
                   'context': ['foo', 'bar', 'baz'],
                   'file': 'foo.js', 'line': 1}

        IGNORABLE_TYPES = ('notice', 'warning')
        OTHER_TYPES = ('error',)

        IGNORABLE_SEVERITIES = ('trivial', 'low')
        OTHER_SEVERITIES = ('medium', 'high')

        def is_ignorable(**kw):
            """Return true if the base message with the given keyword overrides
            is ignorable."""
            msg = merge_dicts(MESSAGE, kw)
            return utils.ValidationComparator.is_ignorable(msg)

        # Non-ignorable types are not ignorable regardless of severity.
        for type_ in OTHER_TYPES:
            for severity in IGNORABLE_SEVERITIES + OTHER_SEVERITIES:
                assert not is_ignorable(signing_severity=severity, type=type_)

        # Non-ignorable severities are not ignorable regardless of type.
        for severity in OTHER_SEVERITIES:
            for type_ in IGNORABLE_TYPES + OTHER_TYPES:
                assert not is_ignorable(signing_severity=severity, type=type_)

        # Ignorable types with ignorable severities are ignorable.
        for severity in IGNORABLE_SEVERITIES:
            for type_ in IGNORABLE_TYPES:
                assert is_ignorable(signing_severity=severity, type=type_)


class TestValidationAnnotatorBase(TestCase):

    def setUp(self):
        # FIXME: Switch to factory_boy.
        # self.file = FileFactory(version__version='1.0')
        # self.file_1_1 = FileFactory(version__version='1.1',
        #                             version__addon=self.file.version.addon)
        # self.file_upload = FileUploadFactory(file=XPIFactory(
        #     guid=self.addon.guid, version=self.xpi_version))

        # Create File objects for version 1.0 and 1.1.
        self.addon = Addon.objects.create(guid='test-desktop@nowhere',
                                          slug='test-amo-addon')

        self.version = Version.objects.create(version='1.0', addon=self.addon)
        self.file = File.objects.create(filename='desktop.xpi',
                                        version=self.version,
                                        status=amo.STATUS_PUBLIC)

        self.version_1_1 = Version.objects.create(version='1.1',
                                                  addon=self.addon)
        self.file_1_1 = File.objects.create(filename='desktop.xpi',
                                            version=self.version_1_1)

        # Creating the files and versions above resets this.
        self.addon.update(status=amo.STATUS_PUBLIC)

        # Create a FileUpload object for an XPI containing version 1.1.
        path = os.path.join(settings.ROOT,
                            'src/olympia/devhub/tests/addons/desktop.xpi')
        self.file_upload = FileUpload.objects.create(path=path)
        self.xpi_version = '1.1'

        # Patch validation tasks that we expect the annotator to call.
        self.patchers = []
        self.save_file = self.patch(
            'olympia.devhub.tasks.handle_file_validation_result').subtask
        self.save_upload = self.patch(
            'olympia.devhub.tasks.handle_upload_validation_result').subtask

        self.validate_file = self.patch(
            'olympia.devhub.tasks.validate_file').subtask
        self.validate_upload = self.patch(
            'olympia.devhub.tasks.validate_file_path').subtask

    def patch(self, thing):
        """Patch the given "thing", and revert the patch on test teardown."""
        patcher = mock.patch(thing)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def check_upload(self, file_, listed=None):
        """Check that our file upload is matched to the given file."""

        # Create an annotator, make sure it matches the expected older file.
        va = utils.ValidationAnnotator(self.file_upload)
        assert va.prev_file == file_

        # Make sure we run the correct validation task for the matched file,
        # if there is a match.
        if file_:
            self.validate_file.assert_called_once_with(
                [file_.pk],
                {'hash_': file_.original_hash, 'is_webextension': False})
        else:
            assert not self.validate_file.called

        # Make sure we run the correct validation task for the upload.
        self.validate_upload.assert_called_once_with(
            [self.file_upload.path],
            {'hash_': self.file_upload.hash, 'listed': listed,
             'is_webextension': False})

        # Make sure we run the correct save validation task, with a
        # fallback error handler.
        self.save_upload.assert_has_calls([
            mock.call([mock.ANY, self.file_upload.pk], {'annotate': False},
                      immutable=True),
            mock.call([self.file_upload.pk], link_error=mock.ANY)])

    def check_file(self, file_new, file_old):
        """Check that the given new file is matched to the given old file."""

        # Create an annotator, make sure it matches the expected older file.
        va = utils.ValidationAnnotator(file_new)
        assert va.prev_file == file_old

        # We shouldn't be attempting to validate a bare upload.
        assert not self.validate_upload.called

        # Make sure we run the correct validation tasks for both files,
        # or only one validation task if there's no match.
        if file_old:
            self.validate_file.assert_has_calls([
                mock.call([file_new.pk], {
                    'hash_': file_new.original_hash,
                    'is_webextension': False}),
                mock.call([file_old.pk], {
                    'hash_': file_old.original_hash,
                    'is_webextension': False})
            ])
        else:
            self.validate_file.assert_called_once_with(
                [file_new.pk],
                {'hash_': file_new.original_hash, 'is_webextension': False})

        # Make sure we run the correct save validation task, with a
        # fallback error handler.
        self.save_file.assert_has_calls([
            mock.call([mock.ANY, file_new.pk], {'annotate': False},
                      immutable=True),
            mock.call([file_new.pk], link_error=mock.ANY)])


class TestValidationAnnotatorUnlisted(TestValidationAnnotatorBase):

    def setUp(self):
        super(TestValidationAnnotatorUnlisted, self).setUp()

        self.addon.update(is_listed=False)

    def test_find_fileupload_prev_version(self):
        """Test that the correct previous version is found for a new upload."""

        self.check_upload(self.file)

    def test_find_file_prev_version(self):
        """Test that the correct previous version is found for a File."""

        self.check_file(self.file_1_1, self.file)

    def test_find_future_fileupload_version(self):
        """Test that a future version will not be matched."""

        self.version.update(version='1.2')

        self.check_upload(None)

    def test_find_future_file(self):
        """Test that a future version will not be matched."""

        self.version.update(version='1.2')

        self.check_file(self.file_1_1, None)

    def test_update_annotations(self):
        """Test that annotations are correctly copied from an old file to a new
        one."""

        HASH_0 = 'xxx'
        HASH_1 = 'yyy'

        RESULTS = deepcopy(amo.VALIDATOR_SKELETON_RESULTS)
        RESULTS['messages'] = [
            {'id': ['foo'],
             'context': ['foo'],
             'file': 'foo'},

            {'id': ['baz'],
             'context': ['baz'],
             'file': 'baz'},
        ]

        self.file.update(original_hash=HASH_0)
        self.file_1_1.update(original_hash=HASH_1)

        # Attach the validation results to our previous version's file,
        # and update the object's cached foreign key value.
        self.file.validation = FileValidation.objects.create(
            file=self.file_1_1, validation=json.dumps(RESULTS))

        def annotation(hash_, key, **kw):
            return ValidationAnnotation(file_hash=hash_, message_key=key, **kw)

        def key(metasyntatic_variable):
            """Return an arbitrary, but valid, message key for the given
            arbitrary string."""
            return '[["{0}"], ["{0}"], "{0}", null, false]'.format(
                metasyntatic_variable)

        # Create two annotations which match the above messages, and
        # one which does not.
        ValidationAnnotation.objects.bulk_create((
            annotation(HASH_0, key('foo'), ignore_duplicates=True),
            annotation(HASH_0, key('bar'), ignore_duplicates=True),
            annotation(HASH_0, key('baz'), ignore_duplicates=False),
        ))

        # Create the annotator and make sure it links our target
        # file to the previous version.
        annotator = utils.ValidationAnnotator(self.file_1_1)
        assert annotator.prev_file == self.file

        annotator.update_annotations()

        # The two annotations which match messages in the above
        # validation results should be duplicated for this version.
        # The third annotation should not.
        assert (set(ValidationAnnotation.objects.filter(file_hash=HASH_1)
                    .values_list('message_key', 'ignore_duplicates')) ==
                set(((key('foo'), True), (key('baz'), False))))


class TestValidationAnnotatorListed(TestValidationAnnotatorBase):

    def test_full_to_full_fileupload(self):
        """Test that a full reviewed version is matched to the nearest
        full reviewed version."""

        self.version_1_1.update(version='1.0.1')
        self.file_1_1.update(status=amo.STATUS_PUBLIC)

        self.check_upload(self.file_1_1)

    def test_full_to_unreviewed(self):
        """Test that a full reviewed version is not matched to an unreviewed
        version."""

        self.file_1_1.update(status=amo.STATUS_UNREVIEWED)
        self.check_upload(self.file)

        # We can't prevent matching against prelim or beta versions
        # until we change the file upload process to allow flagging
        # beta versions prior to validation.

    def test_full_to_full_file(self):
        """Test that a full reviewed version is matched to the nearest
        full reviewed version."""

        self.file_1_1.update(status=amo.STATUS_PUBLIC)

        self.check_file(self.file_1_1, self.file)

        for status in amo.STATUS_UNREVIEWED, amo.STATUS_LITE, amo.STATUS_BETA:
            self.validate_file.reset_mock()
            self.save_file.reset_mock()

            self.file.update(status=status)
            self.check_file(self.file_1_1, None)

    @mock.patch('olympia.devhub.utils.chain')
    def test_run_once_per_file(self, chain):
        """Tests that only a single validation task is run for a given file."""
        task = mock.Mock()
        chain.return_value = task
        task.delay.return_value = mock.Mock(task_id='42')

        assert isinstance(tasks.validate(self.file), mock.Mock)
        assert task.delay.call_count == 1

        assert isinstance(tasks.validate(self.file), AsyncResult)
        assert task.delay.call_count == 1

        assert isinstance(tasks.validate(self.file_1_1), mock.Mock)
        assert task.delay.call_count == 2

    @mock.patch('olympia.devhub.utils.chain')
    def test_run_once_file_upload(self, chain):
        """Tests that only a single validation task is run for a given file
        upload."""
        task = mock.Mock()
        chain.return_value = task
        task.delay.return_value = mock.Mock(task_id='42')

        assert isinstance(tasks.validate(self.file_upload), mock.Mock)
        assert task.delay.call_count == 1

        assert isinstance(tasks.validate(self.file_upload), AsyncResult)
        assert task.delay.call_count == 1

    def test_cache_key(self):
        """Tests that the correct cache key is generated for a given object."""

        assert (utils.ValidationAnnotator(self.file).cache_key ==
                'validation-task:files.File:{0}:None'.format(self.file.pk))

        assert (utils.ValidationAnnotator(self.file_upload, listed=False)
                .cache_key ==
                'validation-task:files.FileUpload:{0}:False'.format(
                    self.file_upload.pk))

    @mock.patch('olympia.devhub.utils.parse_addon')
    def test_search_plugin(self, parse_addon):
        """Test that search plugins are handled correctly."""

        parse_addon.return_value = {'guid': None, 'version': '20140103'}

        addon = addon_factory(type=amo.ADDON_SEARCH,
                              version_kw={'version': '20140101'})

        assert addon.guid is None
        self.check_upload(None)

        self.validate_upload.reset_mock()
        self.save_file.reset_mock()

        version = version_factory(addon=addon, version='20140102')
        self.check_file(version.files.get(), None)


class TestValidationAnnotatorBeta(TestValidationAnnotatorBase):
    def setUp(self):
        super(TestValidationAnnotatorBeta, self).setUp()

        self.xpi_version = '1.1b1'

        parse_addon = self.patch('olympia.devhub.utils.parse_addon')
        parse_addon.return_value = {'version': self.xpi_version,
                                    'guid': self.addon.guid}

    def test_match_beta_to_release(self):
        """Test that a beta submission is matched to the latest approved
        release version."""

        self.check_upload(self.file)

    def test_match_beta_to_signed_beta(self):
        """Test that a beta submission is matched to a prior signed beta
        version."""

        self.file_1_1.update(status=amo.STATUS_BETA, is_signed=True)
        self.version_1_1.update(version='1.1b0')

        self.check_upload(self.file_1_1)

    def test_match_beta_to_unsigned_beta(self):
        """Test that a beta submission is not matched to a prior unsigned beta
        version."""

        self.file_1_1.update(status=amo.STATUS_BETA)
        self.version_1_1.update(version='1.1b0')

        self.check_upload(self.file)


# This is technically in tasks at the moment, but may make more sense as a
# class method of ValidationAnnotator in the future.
class TestAnnotateValidation(TestCase):
    """Test the `annotate_validation_results` task."""

    VALIDATION = {
        'messages': [{'id': ('a', 'b', 'c'),
                      'signing_severity': 'low',
                      'context': ('a', 'b', 'c'),
                      'file': 'foo.js'}]
    }

    def get_validation(self):
        """Return a safe-to-mutate, skeleton validation result set."""
        return deepcopy(self.VALIDATION)

    def test_multiple_validations(self):
        """Test that multiple validations, to be merged by
        ValidationComparator, work."""

        result = annotate_validation_results((self.get_validation(),
                                              self.get_validation()))

        assert (result['messages'][0]['matched'] ==
                self.VALIDATION['messages'][0])

    def test_single_validation(self):
        """Test that passing a single validation result works."""

        result = annotate_validation_results(self.get_validation())

        assert (result['messages'][0]['id'] ==
                self.VALIDATION['messages'][0]['id'])

    def test_signing_summary_added(self):
        """Test that if a signing summary is missing, an empty one is
        added."""

        assert 'signing_summary' not in self.VALIDATION

        result = annotate_validation_results(self.get_validation())
        assert (result['signing_summary'] ==
                {'high': 0, 'medium': 0, 'low': 0, 'trivial': 0})

    def test_passed_based_on_signing_summary(self):
        """Test that the 'passed_auto_validation' flag is correctly added,
        based on signing summary."""

        result = annotate_validation_results(self.get_validation())
        assert result['passed_auto_validation'] is True

        validation = self.get_validation()
        validation['signing_summary'] = {'high': 0, 'medium': 0, 'low': 1,
                                         'trivial': 0}
        result = annotate_validation_results(validation)
        assert result['passed_auto_validation'] is False

        result = annotate_validation_results((self.get_validation(),
                                              self.get_validation()))
        assert result['passed_auto_validation'] is True
        assert (result['signing_summary'] ==
                {'high': 0, 'medium': 0, 'low': 0, 'trivial': 0})
        assert (result['signing_ignored_summary'] ==
                {'high': 0, 'medium': 0, 'low': 1, 'trivial': 0})


class TestLimitValidationResults(TestCase):
    """Test that higher priority messages are truncated last."""

    def make_validation(self, types):
        """Take a list of error types or signing severities and make a
        validation results dict."""
        validation = {
            'messages': [],
            'errors': 0,
            'warnings': 0,
            'notices': 0,
        }
        severities = ['low', 'medium', 'high']
        for type_ in types:
            if type_ in severities:
                severity = type_
                type_ = 'warning'
            else:
                severity = None
            validation[type_ + 's'] += 1
            validation['messages'].append({'type': type_})
            if severity is not None:
                validation['messages'][-1]['signing_severity'] = severity
        return validation

    @override_settings(VALIDATOR_MESSAGE_LIMIT=2)
    def test_errors_are_first(self):
        validation = self.make_validation(
            ['error', 'warning', 'notice', 'error'])
        utils.limit_validation_results(validation)
        limited = validation['messages']
        assert len(limited) == 3
        assert '2 messages were truncated' in limited[0]['message']
        assert limited[1]['type'] == 'error'
        assert limited[2]['type'] == 'error'

    @override_settings(VALIDATOR_MESSAGE_LIMIT=3)
    def test_signing_severity_comes_second(self):
        validation = self.make_validation(
            ['error', 'warning', 'medium', 'notice', 'warning', 'error'])
        utils.limit_validation_results(validation)
        limited = validation['messages']
        assert len(limited) == 4
        assert '3 messages were truncated' in limited[0]['message']
        assert limited[1]['type'] == 'error'
        assert limited[2]['type'] == 'error'
        assert limited[3]['type'] == 'warning'
        assert limited[3]['signing_severity'] == 'medium'


class TestFixAddonsLinterOutput(TestCase):

    def test_fix_output(self):
        original_output = {
            'count': 4,
            'summary': {
                'errors': 0,
                'notices': 0,
                'warnings': 4
            },
            'metadata': {
                'manifestVersion': 2,
                'name': 'My Dogs New Tab',
                'type': 1,
                'version': '2.13.15',
                'architecture': 'extension',
                'emptyFiles': [],
                'jsLibs': {
                    'lib/vendor/jquery.js': 'jquery.2.1.4.jquery.js'
                }
            },
            'errors': [],
            'notices': [],
            'warnings': [
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_PERMISSIONS',
                    'message': '/permissions: Unknown permissions ...',
                    'description': 'See https://mzl.la/1R1n1t0 ...',
                    'file': 'manifest.json'
                },
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_PERMISSIONS',
                    'message': '/permissions: Unknown permissions ...',
                    'description': 'See https://mzl.la/1R1n1t0 ....',
                    'file': 'manifest.json'
                },
                {
                    '_type': 'warning',
                    'code': 'MANIFEST_CSP',
                    'message': '\'content_security_policy\' is ...',
                    'description': 'A custom content_security_policy ...'
                },
                {
                    '_type': 'warning',
                    'code': 'NO_DOCUMENT_WRITE',
                    'message': 'Use of document.write strongly discouraged.',
                    'description': 'document.write will fail in...',
                    'column': 13,
                    'file': 'lib/vendor/knockout.js',
                    'line': 5449
                }
            ]
        }

        fixed = utils.fix_addons_linter_output(original_output)

        assert fixed['success']
        assert fixed['warnings'] == 4
        assert 'uid' in fixed['messages'][0]
        assert 'id' in fixed['messages'][0]
        assert 'type' in fixed['messages'][0]
        assert fixed['messages'][0]['tier'] == 1
        assert fixed['compatibility_summary'] == {
            'warnings': 0,
            'errors': 0,
            'notices': 0,
        }
        assert fixed['ending_tier'] == 5
        assert fixed['signing_summary'] == {
            'low': 0,
            'medium': 0,
            'high': 0,
            'trivial': 0
        }
        assert fixed['metadata']['identified_files'] == {
            'lib/vendor/jquery.js': {'path': 'jquery.2.1.4.jquery.js'}
        }
