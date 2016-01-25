
from amo.tests import TestCase
from zadmin.models import DownloadSource


class TestDownloadSource(TestCase):

    def test_add(self):
        created = DownloadSource.objects.create(
            name='home', type='full',
            description='This is obviously for the homepage')
        d = DownloadSource.objects.filter(id=created.id)
        assert d.count() == 1
        assert d[0].__unicode__() == 'home (full)'
