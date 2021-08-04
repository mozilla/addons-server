import os
from datetime import datetime, timedelta

from unittest import mock

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.core.exceptions import SuspiciousOperation
from django.test.testcases import TransactionTestCase

from olympia.amo.tests import addon_factory, user_factory

from ..models import BlocklistSubmission
from ..tasks import cleanup_old_files, process_blocklistsubmission
from ..utils import datetime_to_ts


def test_cleanup_old_files():
    mlbf_path = settings.MLBF_STORAGE_PATH
    six_month_date = datetime.now() - timedelta(weeks=26)

    now_dir = os.path.join(mlbf_path, str(datetime_to_ts()))
    os.mkdir(now_dir)

    over_six_month_dir = os.path.join(
        mlbf_path, str(datetime_to_ts(six_month_date - timedelta(days=1)))
    )
    os.mkdir(over_six_month_dir)
    with open(os.path.join(over_six_month_dir, 'f'), 'w') as over:
        over.write('.')  # create a file that'll be deleted too

    under_six_month_dir = os.path.join(
        mlbf_path, str(datetime_to_ts(six_month_date - timedelta(days=-1)))
    )
    os.mkdir(under_six_month_dir)

    cleanup_old_files(base_filter_id=9600100364318)  # sometime in the future
    assert os.path.exists(now_dir)
    assert os.path.exists(under_six_month_dir)
    assert not os.path.exists(over_six_month_dir)

    # repeat, but with a base filter id that's over 6 months
    os.mkdir(over_six_month_dir)  # recreate it

    after_base_date_dir = os.path.join(
        mlbf_path, str(datetime_to_ts(six_month_date - timedelta(weeks=1, days=1)))
    )
    os.mkdir(after_base_date_dir)
    with open(os.path.join(after_base_date_dir, 'f'), 'w') as over:
        over.write('.')  # create a file that'll be deleted too

    cleanup_old_files(
        base_filter_id=datetime_to_ts(six_month_date - timedelta(weeks=1))
    )
    assert os.path.exists(now_dir)
    assert os.path.exists(under_six_month_dir)
    assert os.path.exists(over_six_month_dir)
    assert not os.path.exists(after_base_date_dir)


class TestProcessBlocklistSubmission(TransactionTestCase):
    def test_state_reset(self):
        addon_factory(guid='guid@')
        user_factory(id=settings.TASK_USER_ID)

        submission = BlocklistSubmission.objects.create(
            input_guids='guid@', signoff_state=BlocklistSubmission.SIGNOFF_APPROVED
        )
        with mock.patch.object(
            BlocklistSubmission,
            'save_to_block_objects',
            side_effect=SuspiciousOperation('Something happened!'),
        ):
            with self.assertRaises(SuspiciousOperation):
                # we know it's going to raise, we just want to capture it safely
                process_blocklistsubmission.delay(submission.id)
        submission.reload()
        assert submission.signoff_state == BlocklistSubmission.SIGNOFF_PENDING
        log_entry = LogEntry.objects.get()
        assert log_entry.user.id == settings.TASK_USER_ID
        assert log_entry.change_message == 'Exception in task: Something happened!'
