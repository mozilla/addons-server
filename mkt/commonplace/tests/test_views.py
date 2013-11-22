import mock
from nose.tools import eq_

import amo.tests
from amo.utils import reverse


class TestCommonplace(amo.tests.TestCase):

    def test_fireplace(self):
        res = self.client.get('/server.html')
        self.assertTemplateUsed(res, 'commonplace/index.html')
        self.assertEquals(res.context['repo'], 'fireplace')

    def test_commbadge(self):
        res = self.client.get('/comm/')
        self.assertTemplateUsed(res, 'commonplace/index.html')
        self.assertEquals(res.context['repo'], 'commbadge')

    def test_rocketfuel(self):
        res = self.client.get('/curation/')
        self.assertTemplateUsed(res, 'commonplace/index.html')
        self.assertEquals(res.context['repo'], 'rocketfuel')


class TestAppcacheManifest(amo.tests.TestCase):

    def test_no_repo(self):
        res = self.client.get(reverse('commonplace.appcache'))
        eq_(res.status_code, 404)

    def test_bad_repo(self):
        res = self.client.get(reverse('commonplace.appcache'),
                              {'repo': 'rocketfuel'})
        eq_(res.status_code, 404)

    @mock.patch('mkt.commonplace.views.get_build_id', new=lambda x: 'p00p')
    @mock.patch('mkt.commonplace.views.get_imgurls')
    def test_good_repo(self, get_imgurls_mock):
        img = '/media/img/icons/eggs/h1.gif'
        get_imgurls_mock.return_value = [img]
        res = self.client.get(reverse('commonplace.appcache'),
                              {'repo': 'fireplace'})
        eq_(res.status_code, 200)
        assert '# BUILD_ID p00p' in res.content
        img = img.replace('/media/', '/media/fireplace/')
        assert img + '\n' in res.content
