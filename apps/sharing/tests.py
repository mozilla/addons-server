from django import test
from django.contrib.auth.models import User as DjangoUser

import jingo
from mock import Mock
from pyquery import PyQuery as pq

from addons.models import Addon
import sharing
from sharing.helpers import addon_sharing


class SharingHelpersTestCase(test.TestCase):
    fixtures = ['base/addons']

    def test_addon_sharing(self):
        addon = Addon.objects.get(id=7172)

        request = Mock()
        request.user = DjangoUser()
        ctx = {'request': request}

        # disable cake csrf token
        cake_csrf_token = lambda: ''
        cake_csrf_token.__name__ = 'cake_csrf_token'
        jingo.register.function(cake_csrf_token)

        doc = pq(addon_sharing(ctx, addon))
        self.assert_(doc.html())
        self.assertEquals(doc('li').length, len(sharing.SERVICES_LIST))

        # Make sure services are in the right order.
        for i in range(len(sharing.SERVICES_LIST)):
            self.assertEquals(doc('li').eq(i).attr('class'),
                              sharing.SERVICES_LIST[i].shortname)
