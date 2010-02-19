from django.core.urlresolvers import reverse
from django import test

from nose.tools import eq_
import pyquery


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
        actual = pyquery.PyQuery(response.content)('#title').text()
        eq_(expected, actual)

    title_eq('/firefox', 'Add-ons for Firefox')
    title_eq('/thunderbird', 'Add-ons for Thunderbird')
    title_eq('/mobile', 'Mobile Add-ons for Firefox')
