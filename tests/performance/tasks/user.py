import logging
import urlparse
import random

from django.conf import settings
from locust import TaskSet, task
import lxml.html
from fxa import oauth as fxa_oauth

import helpers

log = logging.getLogger(__name__)

MAX_UPLOAD_POLL_ATTEMPTS = 200
FXA_CONFIG = settings.FXA_CONFIG[settings.DEFAULT_FXA_CONFIG_NAME]


class BaseUserTaskSet(TaskSet):

    def on_start(self):
        self.fxa_account, self.email_account = helpers.get_fxa_account()

        log.info(
            'Created {account} for load-tests'
            .format(account=self.fxa_account))

    def is_legacy_page(self, app):
        return app in ('thunderbird', 'seamonkey')

    def get_app(self):
        # Slightly weighted
        app = random.choice(
            ['firefox'] * 20 +
            ['thunderbird'] * 5 +
            ['seamonkey'] * 1)
        return app

    def get_url(self, url, app):
        # Only take a sub-set of languages, doesn't really matter only
        # increases variance and may circumvent some caches here and there
        user_language = random.choice((
            'af', 'de', 'dsb', 'en-US', 'hsb', 'ru', 'tr', 'zh-CN', 'zh-TW'
        ))

        return url.format(app=app, language=user_language)

    def on_stop(self):
        log.info(
            'Cleaning up and destroying {account}'
            .format(account=self.fxa_account))
        helpers.destroy_fxa_account(self.fxa_account, self.email_account)

    def login(self, fxa_account):
        log.debug('calling login/start to generate fxa_state')
        response = self.client.get(
            '/api/v3/accounts/login/start/',
            allow_redirects=True)

        params = dict(urlparse.parse_qsl(response.url))
        fxa_state = params['state']

        log.debug('Get browser id session token')
        fxa_session = helpers.get_fxa_client().login(
            email=fxa_account.email,
            password=fxa_account.password)

        oauth_client = fxa_oauth.Client(
            client_id=FXA_CONFIG['client_id'],
            client_secret=FXA_CONFIG['client_secret'],
            server_url=FXA_CONFIG['oauth_host'])

        log.debug('convert browser id session token into oauth code')
        oauth_code = oauth_client.authorize_code(fxa_session, scope='profile')

        # Now authenticate the user, this will verify the user on the server
        response = self.client.get(
            '/api/v3/accounts/authenticate/',
            params={
                'state': fxa_state,
                'code': oauth_code,
            },
            name='/api/v3/accounts/authenticate/?state=:state'
        )

    def logout(self, account):
        log.debug('Logging out {}'.format(account))
        self.client.get('/en-US/firefox/users/logout/')


class UserTaskSet(BaseUserTaskSet):
    def _browse_listing_and_click_detail(self, listing_url, app,
                                         detail_selector, legacy_selector=None,
                                         name=None, force_legacy=False):
        # TODO: This should hit pagination automatically if there is any
        response = self.client.get(
            self.get_url(listing_url, app),
            allow_redirects=False, catch_response=True)

        if (self.is_legacy_page(app) or force_legacy) and not legacy_selector:
            log.warn(
                'Received legacy url without legacy selector. {} :: {}'
                .format(listing_url, detail_selector))
            return

        if response.status_code == 200:
            html = lxml.html.fromstring(response.content)
            selector = (
                detail_selector
                if not (self.is_legacy_page(app) or force_legacy) else
                legacy_selector)
            collection_links = html.cssselect(selector)

            if not collection_links:
                log.warn(
                    'No selectable links on page. {} :: {}'
                    .format(listing_url, selector))

            url = random.choice(collection_links).get('href')

            kwargs = {}
            if name is not None:
                if self.is_legacy_page(app) or force_legacy:
                    name = name.replace(':app', ':legacy_app')
                kwargs['name'] = name

            self.client.get(url, **kwargs)
            response.success()
        else:
            response.failure('Unexpected status code {}'.format(
                response.status_code))

    @task(8)
    def browse(self):
        app = self.get_app()
        self.client.get(self.get_url('/{language}/{app}/', app))

        self._browse_listing_and_click_detail(
            listing_url='/{language}/{app}/extensions/',
            app=app,
            detail_selector='a.SearchResult-link',
            legacy_selector='.items .item.addon a')

    @task(10)
    def search(self):
        app = self.get_app()

        term_choices = ('Spam', 'Privacy', 'Download')
        term = random.choice(term_choices)
        self.client.get(
            self.get_url(
                '/{language}/{app}/search/?platform=linux&q=' + term,
                app))

    @task(6)
    def browse_and_download_addon(self):
        app = self.get_app()

        self._browse_listing_and_click_detail(
            listing_url='/{language}/{app}/extensions/',
            app=app,
            detail_selector='a.SearchResult-link',
            legacy_selector='.items .item.addon a')

    @task(5)
    def browse_collections(self):
        app = self.get_app()

        # detail and legacy selector match both, themes and regular add-ons
        self._browse_listing_and_click_detail(
            listing_url='/{language}/{app}/',
            app=app,
            detail_selector='a.Home-SubjectShelf-link',
            legacy_selector='.listing-grid .hovercard .summary>a')

    @task(4)
    def browse_categories(self):
        app = self.get_app()

        self._browse_listing_and_click_detail(
            listing_url='/{language}/{app}/extensions/',
            app=app,
            detail_selector='a.Categories-link',
            legacy_selector='ul#side-categories li a')

    @task(4)
    def browse_reviews(self):
        app = self.get_app()

        # TODO: Get add-ons more generalized by looking at collections
        # pages but for now that'll suffice.
        addons = (
            'grammarly-spell-checker', 'clip-to-onenote',
            'evernote-web-clipper', 'reader', 'fractal-summer-colors',
            'abstract-splash', 'colorful-fractal', 'tab-mix-plus')

        for addon in addons:
            self.client.get(self.get_url(
                '/{language}/{app}/addon/%s/reviews/' % addon,
                app))

    @task(4)
    def browse_theme_categories(self):
        app = self.get_app()
        self._browse_listing_and_click_detail(
            listing_url='/{language}/{app}/complete-themes/',
            app=app,
            detail_selector=None,
            legacy_selector='.listing-grid .hovercard>a',
            name='/:lang/:app/complete-themes/:slug/',
            force_legacy=True)

        self._browse_listing_and_click_detail(
            listing_url='/{language}/{app}/themes/',
            app=app,
            detail_selector='a.SearchResult-link',
            legacy_selector='ul#side-categories li a',
            name='/:lang/:app/themes/:slug/')

    @task(3)
    def test_user_profile(self):
        app = self.get_app()

        # TODO: Generalize by actually creating a user-profile and uploading
        # some data.
        usernames = (
            'giorgio-maone', 'wot-services', 'onemen', 'gary-reyes',
            'mozilla-labs5133025', 'gregglind',
            # Has many ratings
            'daveg')

        for user in usernames:
            self.client.get(self.get_url(
                '/{language}/{app}/user/%s/' % user,
                app))

    @task(2)
    def test_rss_feeds(self):
        app = self.get_app()

        urls = (
            # Add-on Category RSS Feed
            '/{language}/firefox/extensions/alerts-updates/format:rss',
            '/{language}/firefox/extensions/appearance/format:rss',
            '/{language}/firefox/extensions/bookmarks/format:rss',
            '/{language}/firefox/extensions/language-support/format:rss',

            # App Version RSS Feed
            '/{language}/{app}/pages/appversions/format:rss',

            # Collection RSS Feed
            '/{language}/firefox/collections/Vivre/ploaia/format:rss',

            # Featured Add-ons
            '/{language}/{app}/featured/format:rss',

            # Search tools RSS Feed
            '/{language}/{app}/search-tools/format:rss',
        )

        self.client.get(self.get_url(random.choice(urls), app))

    @task(1)
    def test_browse_appversions(self):
        app = self.get_app()

        self.client.get(self.get_url(
            '/{language}/{app}/pages/appversions/', app))
