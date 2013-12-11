from django.test.client import RequestFactory
from nose.tools import eq_
from tower import ugettext as _

import amo.tests
from mkt.constants.platforms import FREE_PLATFORMS, PAID_PLATFORMS


class TestPlatforms(amo.tests.TestCase):

    def test_free_platforms_default(self):
        platforms = FREE_PLATFORMS()
        expected = (
            ('free-firefoxos', _('Firefox OS')),
            ('free-desktop', _('Firefox for Desktop')),
            ('free-android-mobile', _('Firefox Mobile')),
            ('free-android-tablet', _('Firefox Tablet')),
        )
        eq_(platforms, expected)

    def test_free_platforms_pkg_waffle_off(self):
        platforms = FREE_PLATFORMS(request=RequestFactory(),
                                   is_packaged=True)
        expected = (
            ('free-firefoxos', _('Firefox OS')),
        )
        eq_(platforms, expected)

    def test_free_platforms_pkg_desktop_waffle_on(self):
        self.create_flag('desktop-packaged')
        platforms = FREE_PLATFORMS(request=RequestFactory(),
                                   is_packaged=True)
        expected = (
            ('free-firefoxos', _('Firefox OS')),
            ('free-desktop', _('Firefox for Desktop')),
        )
        eq_(platforms, expected)

    def test_free_platforms_pkg_android_waffle_on(self):
        self.create_flag('android-packaged')
        platforms = FREE_PLATFORMS(request=RequestFactory(),
                                   is_packaged=True)
        expected = (
            ('free-firefoxos', _('Firefox OS')),
            ('free-android-mobile', _('Firefox Mobile')),
            ('free-android-tablet', _('Firefox Tablet')),
        )
        eq_(platforms, expected)

    def test_free_platforms_pkg_android_and_desktop_waffle_on(self):
        self.create_flag('android-packaged')
        self.create_flag('desktop-packaged')
        platforms = FREE_PLATFORMS(request=RequestFactory(),
                                   is_packaged=True)
        expected = (
            ('free-firefoxos', _('Firefox OS')),
            ('free-desktop', _('Firefox for Desktop')),
            ('free-android-mobile', _('Firefox Mobile')),
            ('free-android-tablet', _('Firefox Tablet')),
        )
        eq_(platforms, expected)

    def test_paid_platforms_default(self):
        platforms = PAID_PLATFORMS()
        expected = (
            ('paid-firefoxos', _('Firefox OS')),
        )
        eq_(platforms, expected)

    def test_paid_platforms_android_payments_waffle_on(self):
        self.create_flag('android-payments')
        platforms = PAID_PLATFORMS(request=RequestFactory())
        expected = (
            ('paid-firefoxos', _('Firefox OS')),
            ('paid-android-mobile', _('Firefox Mobile')),
            ('paid-android-tablet', _('Firefox Tablet')),
        )
        eq_(platforms, expected)

    def test_paid_platforms_pkg_with_android_payments_waffle_on(self):
        self.create_flag('android-payments')
        platforms = PAID_PLATFORMS(request=RequestFactory(),
                                   is_packaged=True)
        expected = (
            ('paid-firefoxos', _('Firefox OS')),
        )
        eq_(platforms, expected)

    def test_paid_platforms_pkg_with_android_payment_pkg_waffle_on(self):
        self.create_flag('android-payments')
        self.create_flag('android-packaged')
        platforms = PAID_PLATFORMS(request=RequestFactory(),
                                   is_packaged=True)
        expected = (
            ('paid-firefoxos', _('Firefox OS')),
            ('paid-android-mobile', _('Firefox Mobile')),
            ('paid-android-tablet', _('Firefox Tablet')),
        )
        eq_(platforms, expected)
