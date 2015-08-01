import os.path
from copy import deepcopy

import mock

from django.conf import settings

import amo
import amo.tests
from addons.models import Addon
from devhub import utils
from devhub.tasks import annotate_validation_results
from files.models import File, FileUpload
from versions.models import Version


def merge_dicts(base, changes):
    res = base.copy()
    res.update(changes)
    return res


class TestValidationComparator(amo.tests.TestCase):
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
        self.expected_msg.update(merge_dicts(self.new_msg, expected_changes))

        results = self.run_comparator(self.old_msg, self.new_msg.copy())

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


class TestValidationAnnotatorBase(amo.tests.TestCase):

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
                            'apps/devhub/tests/addons/desktop.xpi')
        self.file_upload = FileUpload.objects.create(path=path)
        self.xpi_version = '1.1'

        # Patch validation tasks that we expect the annotator to call.
        self.patchers = []
        self.save_file = self.patch(
            'devhub.tasks.handle_file_validation_result').subtask
        self.save_upload = self.patch(
            'devhub.tasks.handle_upload_validation_result').subtask

        self.validate_file = self.patch(
            'devhub.tasks.validate_file').subtask
        self.validate_upload = self.patch(
            'devhub.tasks.validate_file_path').subtask

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()

    def patch(self, thing):
        patcher = mock.patch(thing)
        self.patchers.append(patcher)
        return patcher.start()


class TestValidationAnnotatorUnlisted(TestValidationAnnotatorBase):
    def setUp(self):
        super(TestValidationAnnotatorUnlisted, self).setUp()

        self.addon.update(is_listed=False)

    def test_find_fileupload_prev_version(self):
        """Test that the correct previous version is found for a new upload."""

        va = utils.ValidationAnnotator(self.file_upload)
        assert va.find_previous_version(self.xpi_version) == self.file

        self.validate_file.assert_called_once_with([self.file.pk])

        self.validate_upload.assert_called_once_with(
            [self.file_upload.path, None])

        self.save_upload.assert_called_once_with([self.file_upload.pk])

    def test_find_file_prev_version(self):
        """Test that the correct previous version is found for a File."""

        va = utils.ValidationAnnotator(self.file_1_1)
        assert va.find_previous_version(self.xpi_version) == self.file

        assert not self.validate_upload.called
        self.validate_file.assert_has_calls([mock.call([self.file_1_1.pk]),
                                             mock.call([self.file.pk])])

        self.save_file.assert_called_once_with([self.file_1_1.pk])

    def test_find_future_fileupload_version(self):
        """Test that a future version will not be matched."""

        self.version.update(version='1.2')

        va = utils.ValidationAnnotator(self.file_upload)
        assert va.find_previous_version(self.xpi_version) is None

        assert not self.validate_file.called
        self.validate_upload.assert_called_once_with(
            [self.file_upload.path, None])

        self.save_upload.assert_called_once_with([self.file_upload.pk])

    def test_find_future_file(self):
        """Test that a future version will not be matched."""

        self.version.update(version='1.2')

        va = utils.ValidationAnnotator(self.file_1_1)
        assert va.find_previous_version(self.xpi_version) is None

        assert not self.validate_upload.called
        self.validate_file.assert_called_once_with([self.file_1_1.pk])

        self.save_file.assert_called_once_with([self.file_1_1.pk])


class TestValidationAnnotatorListed(TestValidationAnnotatorBase):

    def test_full_to_full_fileupload(self):
        """Test that a full reviewed version is matched to the nearest
        full reviewed version."""

        self.version_1_1.update(version='1.0.1')

        self.file_1_1.update(status=amo.STATUS_PUBLIC)
        va = utils.ValidationAnnotator(self.file_upload)
        assert va.find_previous_version(self.xpi_version) == self.file_1_1

        self.validate_file.assert_called_once_with([self.file_1_1.pk])
        self.validate_upload.assert_called_once_with(
            [self.file_upload.path, None])
        self.save_upload.assert_called_once_with([self.file_upload.pk])

    def test_full_to_unreviewed(self):
        """Test that a full reviewed version is not matched to an unreviewed
        version."""

        self.file_1_1.update(status=amo.STATUS_UNREVIEWED)
        va = utils.ValidationAnnotator(self.file_upload)
        assert va.find_previous_version(self.xpi_version) == self.file

        self.validate_file.assert_called_once_with([self.file.pk])
        self.validate_upload.assert_called_once_with(
            [self.file_upload.path, None])
        self.save_upload.assert_called_once_with([self.file_upload.pk])

        # We can't prevent matching against prelim or beta versions
        # until we change the file upload process to allow flagging
        # beta versions prior to validation.

    def test_full_to_full_file(self):
        """Test that a full reviewed version is matched to the nearest
        full reviewed version."""

        self.file_1_1.update(status=amo.STATUS_PUBLIC)

        va = utils.ValidationAnnotator(self.file_1_1)
        assert va.find_previous_version(self.xpi_version) == self.file

        self.validate_file.assert_has_calls([mock.call([self.file_1_1.pk]),
                                             mock.call([self.file.pk])])
        self.save_file.assert_called_once_with([self.file_1_1.pk])

        for status in amo.STATUS_UNREVIEWED, amo.STATUS_LITE, amo.STATUS_BETA:
            self.validate_file.reset_mock()
            self.save_file.reset_mock()

            self.file.update(status=status)

            va = utils.ValidationAnnotator(self.file_1_1)
            assert va.find_previous_version(self.xpi_version) is None

            self.validate_file.assert_called_once_with([self.file_1_1.pk])
            self.save_file.assert_called_once_with([self.file_1_1.pk])


class TestValidationAnnotatorBeta(TestValidationAnnotatorBase):

    def setUp(self):
        super(TestValidationAnnotatorBeta, self).setUp()

        self.xpi_version = '1.1b1'

        parse_addon = self.patch('devhub.utils.parse_addon')
        parse_addon.return_value = {'version': self.xpi_version,
                                    'guid': self.addon.guid}

    def test_match_beta_to_release(self):
        """Test that a beta submission is matched to the latest approved
        release version."""

        va = utils.ValidationAnnotator(self.file_upload)
        assert va.find_previous_version(self.xpi_version) == self.file

        self.validate_file.assert_called_once_with([self.file.pk])

    def test_match_beta_to_signed_beta(self):
        """Test that a beta submission is matched to a prior signed beta
        version."""

        self.file_1_1.update(status=amo.STATUS_BETA, is_signed=True)
        self.version_1_1.update(version='1.1b0')

        va = utils.ValidationAnnotator(self.file_upload)
        assert va.find_previous_version(self.xpi_version) == self.file_1_1

        self.validate_file.assert_called_once_with([self.file_1_1.pk])

    def test_match_beta_to_unsigned_beta(self):
        """Test that a beta submission is not matched to a prior unsigned beta
        version."""

        self.file_1_1.update(status=amo.STATUS_BETA)
        self.version_1_1.update(version='1.1b0')

        va = utils.ValidationAnnotator(self.file_upload)
        assert va.find_previous_version(self.xpi_version) == self.file

        self.validate_file.assert_called_once_with([self.file.pk])


# This is technically in tasks at the moment, but may make more sense as a
# class method of ValidationAnnotator in the future.
class TestAnnotateValidation(amo.tests.TestCase):
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
