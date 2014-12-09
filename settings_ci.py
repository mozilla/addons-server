import product_details

from settings import *  # noqa


LOG_LEVEL = logging.ERROR


class MockProductDetails:
    """Main information we need in tests.

    We don't want to rely on the product_details that are automatically
    downloaded in manage.py for the tests. Also, downloading all the
    information is very long, and we don't want that for each test build on
    travis for example.

    So here's a Mock that can be used instead of the real product_details.

    """
    last_update = False
    languages = dict((lang, {'native': lang}) for lang in AMO_LANGUAGES)
    firefox_versions = {"LATEST_FIREFOX_VERSION": "33.1.1"}
    thunderbird_versions = {"LATEST_THUNDERBIRD_VERSION": "31.2.0"}
    firefox_history_major_releases = {'1.0': '2004-11-09'}

    def __init__(self):
        """Some tests need specifics languages.

        This is an excerpt of lib/product_json/languages.json.

        """
        self.languages.update({
            u'el': {
                u'native': u'\u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac',
                u'English': u'Greek'},
            u'hr': {
                u'native': u'Hrvatski',
                u'English': u'Croatian'},
            u'sr': {
                u'native': u'\u0421\u0440\u043f\u0441\u043a\u0438',
                u'English': u'Serbian'},
            u'en-US': {
                u'native': u'English (US)',
                u'English': u'English (US)'},
            u'tr': {
                u'native': u'T\xfcrk\xe7e',
                u'English': u'Turkish'},
            u'cy': {
                u'native': u'Cymraeg',
                u'English': u'Welsh'},
            u'sr-Latn': {
                u'native': u'Srpski',
                u'English': u'Serbian'}})


product_details.product_details = MockProductDetails()
