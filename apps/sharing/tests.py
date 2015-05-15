from django.conf import settings
from django.utils import translation, encoding

import pytest
import tower
from mock import Mock, patch
from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import Addon
import amo
import sharing
import sharing.views
from amo.tests import BaseTestCase
from sharing.forms import ShareForm
from sharing.helpers import sharing_box
from sharing import FACEBOOK

from users.models import UserProfile


pytestmark = pytest.mark.django_db


class SharingHelpersTestCase(BaseTestCase):
    fixtures = ['base/addon_3615']

    def test_sharing_box(self):
        request = Mock()
        request.user = UserProfile()
        request.APP = amo.FIREFOX
        ctx = {'request': request,
               'APP': request.APP,
               'LANG': translation.get_language()}

        doc = pq(sharing_box(ctx))
        self.assert_(doc.html())
        self.assertEquals(doc('li').length, len(sharing.SERVICES_LIST))

        # Make sure services are in the right order.
        for i in range(len(sharing.SERVICES_LIST)):
            self.assertEquals(doc('li').eq(i).attr('class'),
                              sharing.SERVICES_LIST[i].shortname)
            assert doc('li a').eq(i).attr('target') in ('_blank', '_self'), (
                'Sharing link target must either be blank or self.')


class SharingModelsTestCase(BaseTestCase):
    fixtures = ['base/addon_3615', 'sharing/share_counts']

    def test_share_count(self):
        addon = Addon.objects.get(id=3615)
        # total count with no shares
        eq_(addon.share_counts[FACEBOOK.shortname], 0,
            'Total count with no shares must be 0')


def test_services_unicode():
    u = u'\u05d0\u05d5\u05e1\u05e3'
    d = dict(title=u, url=u, description=u)
    for service in sharing.SERVICES_LIST:
        if service.url:
            service.url.format(**d)
    # This does not work since Python tries to use ascii to decode the string.
    # d = dict((k, encoding.smart_str(v)) for k, v in d.items())
    # for service in sharing.SERVICES_LIST:
    #     if service.url:
    #         service.url.format(**d)


def test_share_view():
    u = u'\u05d0\u05d5\u05e1\u05e3'
    s = encoding.smart_str(u)
    request, obj = Mock(), Mock()
    request.GET = {'service': 'twitter'}
    obj.get_url_path.return_value = u
    sharing.views.share(request, obj, u, u)
    obj.get_url_path.return_value = s
    sharing.views.share(request, obj, s, s)


@patch.object(settings, 'SITE_URL', 'http://test')
def test_share_form():
    form = ShareForm({
        'title': 'title',
        'url': '/path/to/nowhere/',
        'description': 'x' * 250 + 'abcdef',
    })
    form.full_clean()
    eq_(form.cleaned_data['description'], 'x' * 250 + '...')
    assert form.cleaned_data['url'].startswith('http'), (
        "Unexpected: URL not absolute")


def test_get_services_in_en_locale():
    # The order is the same as the order of sharing.SERVICES_LIST
    l = ['facebook', 'twitter', 'gplus', 'Reddit', 'Tumblr']
    assert l == [s.shortname for s in sharing.get_services()]


def test_get_services_in_ja_locale():

    testo = sharing.LOCALSERVICE1
    testo.shortname = 'translated-localservice1'

    expected = [
        'facebook',
        'twitter',
        'gplus',
        'Reddit',
        'Tumblr',
        'translated-localservice1']

    with patch.object(sharing, 'LOCALSERVICE1', testo):
        old_locale = translation.get_language()
        try:
            tower.activate('ja')
            assert expected == [s.shortname for s in sharing.get_services()]
        finally:
            tower.activate(old_locale)
