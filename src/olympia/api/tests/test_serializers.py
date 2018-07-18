# -*- coding: utf-8 -*-
from datetime import datetime

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
    assert serializer.handle_date(date.isoformat()) == date.replace(
        microsecond=0
    )
