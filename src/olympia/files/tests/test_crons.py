import os

import pytest

from freezegun import freeze_time

from olympia.files.cron import cleanup_extracted_file
from olympia.files.file_viewer import FileViewer
from olympia.files.tests.test_file_viewer import get_file, make_file


@pytest.mark.django_db
def test_cleanup_extracted_file():
    with freeze_time('2017-01-08 10:01:00'):
        viewer = FileViewer(make_file(1, get_file('webextension.xpi')))

        assert '0108' in viewer.dest
        assert not os.path.exists(viewer.dest)

        viewer.extract()

        assert os.path.exists(viewer.dest)

        # Cleaning up only cleans up yesterdays files so it doesn't touch
        # us today...
        cleanup_extracted_file()

        assert os.path.exists(viewer.dest)

    # Even hours later we don't cleanup yet...
    with freeze_time('2017-01-08 23:59:00'):
        assert os.path.exists(viewer.dest)

        cleanup_extracted_file()

        assert os.path.exists(viewer.dest)

    # But yesterday... we'll cleanup properly
    with freeze_time('2017-01-07 10:01:00'):
        assert os.path.exists(viewer.dest)

        cleanup_extracted_file()

        assert not os.path.exists(viewer.dest)
