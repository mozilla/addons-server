import pytest

from olympia import amo
from olympia.addons.models import Addon
from olympia.files.models import File
from olympia.reviewers.templatetags import code_manager, jinja_helpers
from olympia.versions.models import Version


pytestmark = pytest.mark.django_db


def test_version_status():
    addon = Addon()
    version = Version()
    version.all_files = [
        File(status=amo.STATUS_APPROVED),
        File(status=amo.STATUS_AWAITING_REVIEW),
    ]
    assert 'Approved,Awaiting Review' == (jinja_helpers.version_status(addon, version))

    version.all_files = [File(status=amo.STATUS_AWAITING_REVIEW)]
    assert 'Awaiting Review' == jinja_helpers.version_status(addon, version)


def test_file_review_status_handles_invalid_status_id():
    # When status is a valid one, one of STATUS_CHOICES_FILE return label.
    assert amo.STATUS_CHOICES_FILE[amo.STATUS_APPROVED] == (
        jinja_helpers.file_review_status(None, File(status=amo.STATUS_APPROVED))
    )

    # 99 isn't a valid status, so return the status code for reference.
    status = jinja_helpers.file_review_status(None, File(status=99))
    assert '[status:99]' == status


def test_create_a_code_manager_url():
    assert jinja_helpers.code_manager_url(
        'browse', addon_id=1, base_version_id=2, version_id=3
    ) == code_manager.code_manager_url(
        'browse', addon_id=1, base_version_id=2, version_id=3
    )


def test_format_score():
    assert jinja_helpers.format_score(15.1) == '15%'
    assert jinja_helpers.format_score(0) == 'n/a'
    assert jinja_helpers.format_score(-1) == 'n/a'
