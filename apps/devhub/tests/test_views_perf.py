# -*- coding: utf8 -*-
import json

from mock import patch
from nose.tools import eq_

from addons.models import Addon
from amo.urlresolvers import reverse
import amo.tests
from files.models import Platform


class TestPerfViews(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/platforms',
                'base/addon_3615']

    def setUp(self):
        super(TestPerfViews, self).setUp()
        assert self.client.login(username='del@icio.us', password='password')
        addon = Addon.objects.get(pk=3615)
        self.file = addon.latest_version.files.get()
        self.patches = [patch('waffle.flag_is_active'),
                        patch('waffle.helpers.flag_is_active')]
        for p in self.patches:
            p.start().return_value = True
        p = patch('devhub.perf.start_perf_test')
        self.perf_test = p.start()
        self.patches.append(p)
        self.perf_calls = None

    def tearDown(self):
        super(TestPerfViews, self).tearDown()
        for p in self.patches:
            p.stop()

    def assert_call(self, expected_call):
        if not self.perf_calls:
            self.perf_calls = [tuple(c) for c in
                               self.perf_test.call_args_list]
        assert expected_call in self.perf_calls, (
                                'Call was not made: %s' % str(expected_call))

    def start(self):
        re = self.client.get(reverse('devhub.file_perf_tests_start',
                             args=[self.file.version.addon.id, self.file.id]),
                             follow=True)
        eq_(re.status_code, 200)
        return json.loads(re.content)

    def set_platform(self, platform):
        self.file.update(platform=Platform.objects.get(pk=platform.id))

    def test_start_linux(self):
        self.set_platform(amo.PLATFORM_LINUX)
        re = self.start()
        eq_(re, {'success': True})
        self.assert_call(((self.file, 'linux', 'firefox3.6'), {}))
        self.assert_call(((self.file, 'linux', 'firefox6.0'), {}))

    def test_start_all(self):
        self.set_platform(amo.PLATFORM_ALL)
        self.start()
        self.assert_call(((self.file, 'linux', 'firefox6.0'), {}))

    def test_unsupported_plat(self):
        self.set_platform(amo.PLATFORM_ANDROID)
        eq_(self.start(), {'success': False})
