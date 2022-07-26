import pytest

from olympia.reviewers.templatetags import code_manager, jinja_helpers


pytestmark = pytest.mark.django_db


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
