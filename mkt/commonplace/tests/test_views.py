import amo.tests


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
        res = self.client.get('/rocketfuel/')
        self.assertTemplateUsed(res, 'commonplace/index.html')
        self.assertEquals(res.context['repo'], 'rocketfuel')
