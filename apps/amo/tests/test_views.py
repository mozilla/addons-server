from django.core.urlresolvers import reverse
from django import test

from nose.tools import eq_
from pyquery import PyQuery
import test_utils


def test_404_no_app():
    """Make sure a 404 without an app doesn't turn into a 500."""
    # That could happen if helpers or templates expect APP to be defined.
    url = reverse('amo.monitor')
    response = test.Client().get(url + 'nonsense')
    eq_(response.status_code, 404)


def test_heading():
    c = test.Client()
    def title_eq(url, expected):
        response = c.get(url, follow=True)
        actual = PyQuery(response.content)('#title').text()
        eq_(expected, actual)

    title_eq('/firefox', 'Add-ons for Firefox')
    title_eq('/thunderbird', 'Add-ons for Thunderbird')
    title_eq('/mobile', 'Mobile Add-ons for Firefox')


class TestStuff(test_utils.TestCase):
    fixtures = ['base/addons']

    def test_data_anonymous(self):
        def check(expected):
            response = self.client.get('/', follow=True)
            anon = PyQuery(response.content)('body').attr('data-anonymous')
            eq_(anon, expected)

        check('1')
        self.client.login(username='admin@mozilla.com', password='password')
        check('0')

    def test_my_account_menu(self):
        def check(expected):
            response = self.client.get('/', follow=True)
            account = PyQuery(response.content)('ul.account')
            tools = PyQuery(response.content)('ul.tools')
            eq_(account.size(), expected)
            eq_(tools.size(), expected)

        check(0)
        self.client.login(username='admin@mozilla.com', password='password')
        check(1)
