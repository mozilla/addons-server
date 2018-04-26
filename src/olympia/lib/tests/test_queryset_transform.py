from datetime import datetime

from django.db import models

from olympia.amo.tests import TestCase
from olympia.lib.queryset_transform import TransformQuerySetMixin
from olympia.zadmin.models import SiteEvent


class TransformQuerySet(TransformQuerySetMixin, models.QuerySet):
    pass


class QuerysetTransformTestCase(TestCase):
    def test_queryset_transform(self):
        # We test with the SiteEvent model because it's a simple model
        # with no translated fields, no caching or other fancy features.
        SiteEvent.objects.create(start=datetime.now(), description='Zero')
        first = SiteEvent.objects.create(start=datetime.now(),
                                         description='First')
        second = SiteEvent.objects.create(start=datetime.now(),
                                          description='Second')
        SiteEvent.objects.create(start=datetime.now(), description='Third')
        SiteEvent.objects.create(start=datetime.now(), description='')

        seen_by_first_transform = []
        seen_by_second_transform = []
        with self.assertNumQueries(0):
            # No database hit yet, everything is still lazy.
            qs = TransformQuerySet(SiteEvent)
            qs = qs.exclude(description='').order_by('id')[1:3]
            qs = qs.transform(
                lambda items: seen_by_first_transform.extend(list(items)))
            qs = qs.transform(
                lambda items: seen_by_second_transform.extend(
                    list(reversed(items))))
        with self.assertNumQueries(1):
            assert list(qs) == [first, second]
        # Check that each transform function was hit correctly, once.
        assert seen_by_first_transform == [first, second]
        assert seen_by_second_transform == [second, first]
