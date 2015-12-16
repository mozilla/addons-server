from nose.tools import eq_

from olympia.amo.tests import TestCase
from olympia.zadmin.models import DownloadSource


class TestDownloadSource(TestCase):

    def test_add(self):
        created = DownloadSource.objects.create(
            name='home', type='full',
            description='This is obviously for the homepage')
        d = DownloadSource.objects.filter(id=created.id)
        eq_(d.count(), 1)
        eq_(d[0].__unicode__(), 'home (full)')
