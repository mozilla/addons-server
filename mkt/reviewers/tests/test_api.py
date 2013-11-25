import json
from datetime import datetime

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache

from nose.tools import eq_
from test_utils import RequestFactory

import amo
import mkt.regions
from access.models import GroupUser
from addons.models import Category
from amo.tests import ESTestCase
from amo.urlresolvers import reverse
from users.models import UserProfile

from mkt.api.base import list_url
from mkt.api.models import Access, generate
from mkt.api.tests.test_oauth import BaseOAuth, OAuthClient, RestOAuth
from mkt.constants.features import FeatureProfile
from mkt.reviewers.api import ReviewersSearchResource
from mkt.reviewers.utils import AppsReviewing
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestReviewing(RestOAuth):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestReviewing, self).setUp()
        self.list_url = reverse('reviewing-list')
        self.user = UserProfile.objects.get(pk=2519)
        self.req = RequestFactory().get('/')
        self.req.amo_user = self.user

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ('get'))

    def test_not_allowed(self):
        eq_(self.anon.get(self.list_url).status_code, 403)

    def test_still_not_allowed(self):
        eq_(self.client.get(self.list_url).status_code, 403)

    def add_perms(self):
        self.grant_permission(self.user, 'Apps:Review')

    def test_allowed(self):
        self.add_perms()
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200, res.content)
        data = json.loads(res.content)
        eq_(data['objects'], [])

    def test_some(self):
        self.add_perms()

        # This feels rather brittle.
        cache.set('%s:review_viewing:%s' % (settings.CACHE_PREFIX, 337141),
                  2519, 50 * 2)
        AppsReviewing(self.req).add(337141)

        res = self.client.get(self.list_url)
        data = json.loads(res.content)
        eq_(data['objects'][0]['resource_uri'],
            reverse('app-detail', kwargs={'pk': 337141}))


class TestApiReviewer(BaseOAuth, ESTestCase):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self, api_name='reviewers'):
        super(TestApiReviewer, self).setUp(api_name=api_name)
        self.user = User.objects.get(pk=2519)
        self.profile = self.user.get_profile()
        self.profile.update(read_dev_agreement=datetime.now())
        self.grant_permission(self.profile, 'Apps:Review')

        self.access = Access.objects.create(
            key='test_oauth_key', secret=generate(), user=self.user)
        self.client = OAuthClient(self.access, api_name=api_name)
        self.url = list_url('search')

        self.webapp = Webapp.objects.get(pk=337141)
        self.category = Category.objects.create(name='test',
                                                type=amo.ADDON_WEBAPP)

        self.webapp.update(status=amo.STATUS_PENDING)
        self.refresh('webapp')

    def test_fields(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        self.assertSetEqual(obj.keys(), ReviewersSearchResource._meta.fields)

    def test_anonymous_access(self):
        res = self.anon.get(self.url)
        eq_(res.status_code, 401)

    def test_non_reviewer_access(self):
        GroupUser.objects.filter(group__rules='Apps:Review',
                                 user=self.profile).delete()
        res = self.client.get(self.url)
        eq_(res.status_code, 401)

    def test_owner_still_non_reviewer_access(self):
        user = Webapp.objects.get(pk=337141).authors.all()[0].user
        access = Access.objects.create(
            key='test_oauth_key_owner', secret=generate(), user=user)
        client = OAuthClient(access, api_name='reviewers')
        res = client.get(self.url)
        eq_(res.status_code, 401)

    def test_status(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'pending'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'rejected'},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

        self.webapp.update(status=amo.STATUS_REJECTED)
        self.refresh('webapp')

        res = self.client.get(self.url + ({'status': 'rejected'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        self.webapp.update(status=amo.STATUS_PUBLIC)
        self.refresh('webapp')

        res = self.client.get(self.url + ({'status': 'public'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'any'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'status': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = res.json['error_message']
        eq_(error.keys(), ['status'])

    def test_is_escalated(self):
        res = self.client.get(self.url + ({'is_escalated': True},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.url + ({'is_escalated': False},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'is_escalated': None},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_has_editors_comment(self):
        res = self.client.get(self.url + ({'has_editor_comment': True},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.url + ({'has_editor_comment': False},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'has_editor_comment': None},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_has_info_request(self):
        res = self.client.get(self.url + ({'has_info_request': True},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.url + ({'has_info_request': False},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'has_info_request': None},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_addon_type(self):
        res = self.client.get(self.url + ({'type': 'app'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

        res = self.client.get(self.url + ({'type': 'theme'},))
        eq_(res.status_code, 200)
        objs = res.json['objects']
        eq_(len(objs), 0)

        res = self.client.get(self.url + ({'type': 'vindaloo'},))
        eq_(res.status_code, 400)
        error = res.json['error_message']
        eq_(error.keys(), ['type'])

    def test_no_region_filtering(self):
        self.webapp.addonexcludedregion.create(region=mkt.regions.BR.id)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + ({'region': 'br'},))
        eq_(res.status_code, 200)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_no_feature_profile_filtering(self):
        feature_profile = FeatureProfile().to_signature()
        qs = {'q': 'something', 'pro': feature_profile, 'dev': 'firefoxos'}

        # Enable an app feature that doesn't match one in our profile.
        self.webapp.current_version.features.update(has_pay=True)
        self.webapp.save()
        self.refresh('webapp')

        res = self.client.get(self.url + (qs,))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)
        obj = res.json['objects'][0]
        eq_(obj['slug'], self.webapp.app_slug)

    def test_no_flash_filtering(self):
        f = self.webapp.get_latest_file()
        f.uses_flash = True
        f.save()
        self.webapp.save()
        self.refresh('webapp')
        res = self.client.get(self.url + ({'dev': 'firefoxos'},))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)

    def test_no_premium_filtering(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        self.refresh('webapp')
        res = self.client.get(self.url + ({'dev': 'android'},))
        eq_(res.status_code, 200)
        eq_(len(res.json['objects']), 1)


class TestApproveRegion(RestOAuth):
    fixtures = fixture('user_2519', 'webapp_337141')

    def url(self, **kwargs):
        kw = {'pk': '337141', 'region': 'cn'}
        kw.update(kwargs)
        return reverse('approve-region', kwargs=kw)

    def test_verbs(self):
        self.grant_permission(self.profile, 'Apps:ReviewRegionCN')
        self._allowed_verbs(self.url(), ['post'])

    def test_anon(self):
        res = self.anon.post(self.url())
        eq_(res.status_code, 403)

    def test_bad_webapp(self):
        self.grant_permission(self.profile, 'Apps:ReviewRegionCN')
        res = self.client.post(self.url(pk='999'))
        eq_(res.status_code, 404)

    def test_webapp_not_pending_in_region(self):
        self.grant_permission(self.profile, 'Apps:ReviewRegionCN')
        res = self.client.post(self.url())
        eq_(res.status_code, 404)

    def test_good_but_no_permission(self):
        res = self.client.post(self.url())
        eq_(res.status_code, 403)

    def test_good_webapp_but_wrong_region_permission(self):
        self.grant_permission(self.profile, 'Apps:ReviewRegionBR')

        app = Webapp.objects.get(id=337141)
        app.geodata.set_status('cn', amo.STATUS_PENDING, save=True)

        res = self.client.post(self.url())
        eq_(res.status_code, 403)

    def test_good_webapp_but_wrong_region_queue(self):
        self.grant_permission(self.profile, 'Apps:ReviewRegionCN')

        app = Webapp.objects.get(id=337141)
        app.geodata.set_status('cn', amo.STATUS_PENDING, save=True)

        res = self.client.post(self.url(region='br'))
        eq_(res.status_code, 403)

    def test_good_rejected(self):
        self.grant_permission(self.profile, 'Apps:ReviewRegionCN')

        app = Webapp.objects.get(id=337141)
        app.geodata.set_status('cn', amo.STATUS_PENDING, save=True)

        res = self.client.post(self.url())
        eq_(res.status_code, 200)
        obj = json.loads(res.content)
        eq_(obj['approved'], False)
        eq_(app.geodata.reload().get_status('cn'), amo.STATUS_REJECTED)

    def test_good_approved(self):
        self.grant_permission(self.profile, 'Apps:ReviewRegionCN')

        app = Webapp.objects.get(id=337141)
        app.geodata.set_status('cn', amo.STATUS_PENDING, save=True)

        res = self.client.post(self.url(), data=json.dumps({'approve': '1'}))
        eq_(res.status_code, 200)
        obj = json.loads(res.content)
        eq_(obj['approved'], True)
        eq_(app.geodata.reload().get_status('cn'), amo.STATUS_PUBLIC)
