import pytest

from olympia.core.tests.db_tests_testapp.models import TestRegularCharField


@pytest.mark.django_db
@pytest.mark.parametrize('value', [
    'a',
    '🔍',  # \U0001f50d
    '❤',  # Regular red heart emoji (\u27640)
])
def test_max_length_utf8mb4(value):
    TestRegularCharField.objects.create(name=value * 255)

    assert TestRegularCharField.objects.get().name == value * 255
