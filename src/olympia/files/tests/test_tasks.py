# -*- coding: utf8 -*-
import mock
from datetime import datetime, timedelta

from django.test.utils import override_settings

from olympia import amo
from olympia.files import tasks
from olympia.files.models import File
from olympia.versions.models import Version


# Very basic js file that contains a `let`, a `const`, and a `var` in the
# toplevel scope. Both the `let` and `const` should be rewritten to `var`.
TEST_JS_FILE = 'src/olympia/files/fixtures/files/test_with_toplevel_let.js'


def assert_test_file_fixed(filename):
    """Check that the content of the "test file" has been fixed."""
    with open(filename, 'r') as fixed_js_file:
        # The "let foo = 1;" has been "fixed" to "var foo = 1".
        expected = "var foo = 1;\nvar   bar = 2;\nvar baz = 3;\n"
        assert fixed_js_file.read() == expected


def test_fix_let_scope_bustage():
    # Create two copies, we want to make sure the fixage script fixes both.
    with amo.tests.copy_file_to_temp(TEST_JS_FILE) as temp_filename1:
        with amo.tests.copy_file_to_temp(TEST_JS_FILE) as temp_filename2:
            # No output, no error.
            assert tasks.fix_let_scope_bustage(temp_filename1,
                                               temp_filename2) == ('', '')
            assert_test_file_fixed(temp_filename1)
            assert_test_file_fixed(temp_filename2)


@mock.patch('olympia.files.tasks.fix_let_scope_bustage')
def test_fix_let_scope_bustage_in_xpi(mock_fixer):
    """Fix the "let scope bustage" in the test XPI.

    The content of the test XPI is as follows:
    ├── chrome.manifest
    ├── foobar
    │   └── main.js
    ├── install.rdf
    └── some_file.js

    The two files that should be fixed are some_file.js and foobar/main.js.
    Both those files have the same content as the TEST_JS_FILE.
    """
    test_xpi = 'src/olympia/files/fixtures/files/extension-let-global-scope.xpi'
    with amo.tests.copy_file_to_temp(test_xpi) as temp_filename:
        tasks.fix_let_scope_bustage_in_xpi(temp_filename)
    mock_fixer.assert_called_once_with(mock.ANY, mock.ANY)
    # Make sure it's been called with the two javascript files in the xpi.
    call = mock_fixer.call_args[0]
    assert call[0].endswith('some_file.js')
    assert call[1].endswith('foobar/main.js')


@mock.patch('olympia.files.tasks.fix_let_scope_bustage_in_xpi')
@mock.patch('olympia.files.tasks.update_version_number')
@mock.patch('olympia.files.tasks.sign_file')
def test_fix_let_scope_bustage_in_addon(mock_sign_file, mock_version_bump,
                                        mock_fixer, db):
    # Create an add-on, with a version.
    addon = amo.tests.addon_factory()
    addon.update(guid='xxxxx')
    # Add another version, which is the one we want to fix.
    version = Version.objects.create(addon=addon, version='0.1')
    # So addon.versions.first() (which is the last one uploaded) works.
    future_date = datetime.now() + timedelta(days=1)
    version.update(created=future_date)
    assert addon.versions.count() == 2  # Two versions, we only fix the last.

    # Assign a file for the last version's file.
    test_xpi = 'src/olympia/files/fixtures/files/extension-let-global-scope.xpi'
    file_ = File.objects.create(version=version, filename='foo.xpi',
                                is_signed=True)
    with override_settings(PRELIMINARY_SIGNING_SERVER='prelim_signing'):
        with amo.tests.copy_file(test_xpi, file_.file_path):
            # Fix the file!
            tasks.fix_let_scope_bustage_in_addons([addon.pk])

    # fix_let_scope_bustage_in_xpi was called.
    mock_fixer.assert_called_once_with(file_.file_path)

    # Version was bumped.
    bumped_version_number = u'0.1.1-let-fixed'
    version.reload().version == bumped_version_number
    mock_version_bump.assert_called_once_with(file_, bumped_version_number)

    # File was signed.
    mock_sign_file.assert_called_once_with(file_, 'prelim_signing')
