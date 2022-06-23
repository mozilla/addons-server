from datetime import datetime

from importlib import import_module
import pytest

from django.conf import settings

from rest_framework.serializers import BaseSerializer

from olympia.addons.models import Addon
from olympia.api.serializers import BaseESSerializer


class BasicSerializer(BaseESSerializer):
    class Meta:
        model = Addon
        fields = ()


def test_handle_date_strips_microseconds():
    serializer = BasicSerializer()
    date = datetime.utcnow()
    assert date.microsecond
    assert serializer.handle_date(date.isoformat()) == date.replace(microsecond=0)


def find_all_serializers_with_read_only_fields():
    for app in settings.INSTALLED_APPS:
        if not app.startswith('olympia'):
            continue
        try:
            serializers = import_module(f'{app}.serializers')
        except ModuleNotFoundError:
            continue
        for name in dir(serializers):
            item = getattr(serializers, name)
            if (
                hasattr(item, 'mro')
                and BaseSerializer in item.mro()
                and hasattr(item, 'Meta')
                and hasattr(item.Meta, 'read_only_fields')
            ):
                yield item


@pytest.mark.parametrize(
    'serializer_class', find_all_serializers_with_read_only_fields()
)
def test_serializer_read_only_fields(serializer_class):
    """On all serializers we can find (using <app>/serializers.py on all
    installed apps), ensure fields in read_only_fields are really read_only.

    Safety net for https://github.com/encode/django-rest-framework/issues/3533
    """
    serializer = serializer_class()
    fields_read_only = {
        name for name, field in serializer.get_fields().items() if field.read_only
    }
    assert fields_read_only == set(serializer.Meta.read_only_fields), (
        f'{serializer_class} has fields not set as read_only despite being in '
        f'{serializer_class}.Meta.read_only_fields !'
    )
