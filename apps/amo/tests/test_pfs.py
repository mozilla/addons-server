import amo
import amo.tests
from services.pfs import get_output

from  pyquery import PyQuery as pq


class TestPfs(amo.tests.TestCase):

    def test_xss(self):
        for k in ['name', 'mimetype', 'guid', 'version', 'iconUrl',
                  'InstallerLocation', 'InstallerHash', 'XPILocation',
                  'InstallerShowsUI', 'manualInstallationURL',
                  'licenseURL', 'needsRestart']:
            res = get_output({k: 'fooo<script>alert("foo")</script>;'})
            assert not pq(res)('script')
