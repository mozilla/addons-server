from django.conf import settings
from test_utils import SeleniumTestCase


class TestLogin(SeleniumTestCase):

    fixtures = ['users/test_backends']

    def test_login(self):
        sel = self.selenium
        sel.open("%s/en-US/admin" % settings.SITE_URL)
        sel.type("id_username", "fligtar@gmail.com")
        sel.type("id_password", "foo")
        sel.click("css=.submit-row .input[type=submit]")
        sel.wait_for_page_to_load(5000)
        self.assertEqual("Site administration :: AMO Admin", sel.get_title())
