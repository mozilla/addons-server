from olympia.amo.tests import TestCase
from olympia.lib.queryset_transform import TransformQuerySet
from olympia.zadmin.models import DownloadSource


class QuerysetTransformTestCase(TestCase):
    def test_queryset_transform(self):
        # We test with the DownloadSource model because it's a simple model
        # with no translated fields, no caching or other fancy features.
        DownloadSource.objects.create(name='Zero')
        first = DownloadSource.objects.create(name='First')
        second = DownloadSource.objects.create(name='Second')
        DownloadSource.objects.create(name='Third')
        DownloadSource.objects.create(name='')

        seen_by_first_transform = []
        seen_by_second_transform = []
        with self.assertNumQueries(0):
            # No database hit yet, everything is still lazy.
            qs = TransformQuerySet(DownloadSource)
            qs = qs.exclude(name='').order_by('id')[1:3]
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
