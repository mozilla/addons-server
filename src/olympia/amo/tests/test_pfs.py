from pyquery import PyQuery as pq
from services.pfs import get_output

from olympia.amo.tests import TestCase


class TestPfs(TestCase):

    def test_xss(self):
        for k in ['name', 'mimetype', 'guid', 'version', 'iconUrl',
                  'InstallerLocation', 'InstallerHash', 'XPILocation',
                  'InstallerShowsUI', 'manualInstallationURL',
                  'licenseURL', 'needsRestart']:
            res = get_output({k: 'fooo<script>alert("foo")</script>;'})
            assert not pq(res)('script')
