from datetime import date, timedelta

from django import test
from django.contrib.auth.models import User as DjangoUser
from django.utils import translation

import jingo
from mock import Mock
from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import Addon
import amo
import sharing
from sharing.helpers import addon_sharing
from sharing.models import DIGG, FACEBOOK
from stats.models import ShareCount


class SharingHelpersTestCase(test.TestCase):
    fixtures = ['base/addons']

    def test_addon_sharing(self):
        addon = Addon.objects.get(id=7172)

        jingo.load_helpers()

        request = Mock()
        request.user = DjangoUser()
        request.APP = amo.FIREFOX
        ctx = {'request': request,
               'APP': request.APP,
               'LANG': translation.get_language()}

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


class SharingModelsTestCase(test.TestCase):
    fixtures = ['base/addons']

    def test_share_count(self):
        addon = Addon.objects.get(id=7172)

        # add shares, then check aggregate
        mycounts = (5, 2, 7, 0, 3)
        for i in range(len(mycounts)):
            ShareCount.objects.create(
                addon=addon, count=mycounts[i], date=date.today()-timedelta(i),
                service=DIGG.shortname)
        eq_(DIGG.share_count(addon), sum(mycounts))

        # total count with no shares
        eq_(FACEBOOK.share_count(addon), 0,
            'Total count with no shares must be 0')
