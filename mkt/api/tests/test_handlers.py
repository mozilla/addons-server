from decimal import Decimal
import json
import os
from StringIO import StringIO
import tempfile

from django.core.urlresolvers import reverse
from mock import patch
from nose.tools import eq_

import amo
from access.models import Group, GroupUser
from addons.models import (Addon, AddonDeviceType, AddonUpsell,
                           AddonUser, Category, Preview)
from amo.tests import AMOPaths, app_factory, TestCase
from files.models import FileUpload
from market.models import Price, PriceCurrency
from tags.models import AddonTag, Tag
from users.models import UserProfile

from mkt.api.models import Access, generate
from mkt.api.tests.test_oauth import RestOAuthClient, RestOAuth
from mkt.constants import ratingsbodies, regions
from mkt.webapps.api import LargeTextField
from mkt.site.fixtures import fixture
from mkt.webapps.models import AddonExcludedRegion, Webapp
from reviews.models import Review


class CreateHandler(RestOAuth):
    fixtures = fixture('user_2519', 'platform_all')

    def setUp(self):
        super(CreateHandler, self).setUp()
        self.list_url = reverse('app-list')
        self.user = UserProfile.objects.get(pk=2519)
        self.file = tempfile.NamedTemporaryFile('w', suffix='.webapp').name
        self.manifest_copy_over(self.file, 'mozball-nice-slug.webapp')
        self.categories = []
        for x in range(0, 2):
            self.categories.append(Category.objects.create(
                name='cat-%s' % x,
                slug='cat-%s' % x,
                type=amo.ADDON_WEBAPP))

    def create(self, fil=None):
        if fil is None:
            fil = self.file
        return FileUpload.objects.create(user=self.user, path=fil,
                                         name=fil, valid=True)


def _mock_fetch_content(url):
    return open(os.path.join(os.path.dirname(__file__),
                             '..', '..', 'developers', 'tests', 'icons',
                             '337141-128.png'))


class TestAppCreateHandler(CreateHandler, AMOPaths):
    fixtures = fixture('app_firefox', 'platform_all', 'user_admin',
                       'user_2519', 'user_999')

    def count(self):
        return Addon.objects.count()

    def test_verbs(self):
        self.create()
        self._allowed_verbs(self.list_url, ['get', 'post'])
        self.create_app()
        self._allowed_verbs(self.get_url, ['get', 'put', 'delete'])

    def test_not_accepted_tos(self):
        self.user.update(read_dev_agreement=None)
        obj = self.create()
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest': obj.uuid}))
        eq_(res.status_code, 403)

    def test_not_valid(self):
        obj = self.create()
        obj.update(valid=False)
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest': obj.uuid}))
        eq_(res.status_code, 400)
        eq_(res.json['detail'], 'Upload not valid.')
        eq_(self.count(), 0)

    def test_not_there(self):
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest':
                                   'some-random-32-character-stringy'}))
        eq_(res.status_code, 400)
        eq_(res.json['detail'], 'No upload found.')
        eq_(self.count(), 0)

    def test_anon(self):
        obj = self.create()
        obj.update(user=None)
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest': obj.uuid}))
        eq_(res.status_code, 403)
        eq_(self.count(), 0)

    def test_not_yours(self):
        obj = self.create()
        obj.update(user=UserProfile.objects.get(email='admin@mozilla.com'))
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest': obj.uuid}))
        eq_(res.status_code, 403)
        eq_(self.count(), 0)

    @patch('mkt.webapps.api.record_action')
    def test_create(self, record_action):
        obj = self.create()
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest': obj.uuid}))
        eq_(res.status_code, 201)
        content = json.loads(res.content)
        eq_(content['status'], 0)
        eq_(content['slug'], u'mozillaball')
        eq_(content['support_email'], None)
        eq_(self.count(), 1)

        app = Webapp.objects.get(app_slug=content['slug'])
        eq_(set(app.authors.all()), set([self.user]))
        assert record_action.called

    def create_app(self, fil=None):
        obj = self.create(fil)
        res = self.client.post(self.list_url,
                               data=json.dumps({'manifest': obj.uuid}))
        pk = json.loads(res.content)['id']
        self.get_url = reverse('app-detail', kwargs={'pk': pk})
        return Webapp.objects.get(pk=pk)

    def test_upsell(self):
        app = self.create_app()
        upsell = app_factory()
        self.make_premium(upsell)
        AddonUpsell.objects.create(free=app, premium=upsell)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        obj = json.loads(res.content)['upsell']
        eq_(obj['id'], upsell.id)
        eq_(obj['app_slug'], upsell.app_slug)
        eq_(obj['name'], upsell.name)
        eq_(obj['icon_url'], upsell.get_icon_url(128))
        eq_(obj['resource_uri'],
            reverse('app-detail', kwargs={'pk': upsell.id}))

    def test_get(self):
        self.create_app()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        content = json.loads(res.content)
        eq_(content['status'], 0)

    def test_get_slug(self):
        app = self.create_app()
        url = reverse('app-detail', kwargs={'pk': app.app_slug})
        res = self.client.get(url)
        content = json.loads(res.content)
        eq_(content['id'], app.pk)

    def test_list(self):
        app = self.create_app()
        res = self.client.get(self.list_url)
        eq_(res.status_code, 200)
        content = json.loads(res.content)
        eq_(content['meta']['total_count'], 1)
        eq_(content['objects'][0]['id'], app.pk)

    def test_list_anon(self):
        eq_(self.anon.get(self.list_url).status_code, 403)

    def test_get_device(self):
        app = self.create_app()
        AddonDeviceType.objects.create(addon=app,
                                       device_type=amo.DEVICE_DESKTOP.id)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        content = json.loads(res.content)
        eq_(content['device_types'], [u'desktop'])

    def test_not_public(self):
        self.create_app()
        res = self.anon.get(self.get_url)
        eq_(res.status_code, 403)

    def test_get_public(self):
        app = self.create_app()
        app.update(status=amo.STATUS_PUBLIC)
        res = self.anon.get(self.get_url)
        eq_(res.status_code, 200)

    def test_get_previews(self):
        app = self.create_app()
        res = self.client.get(self.get_url)
        eq_(len(json.loads(res.content)['previews']), 0)
        Preview.objects.create(addon=app)
        res = self.client.get(self.get_url)
        eq_(len(json.loads(res.content)['previews']), 1)

    def test_get_not_mine(self):
        obj = self.create_app()
        obj.authors.clear()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 403)

    def test_get_privacy_policy(self):
        app = self.create_app()
        data = self.base_data()
        self.client.put(self.get_url, data=json.dumps(data))
        res = self.client.get(reverse('app-privacy-policy-detail',
                                      args=[app.pk]))
        eq_(res.json['privacy_policy'], data['privacy_policy'])

    def test_get_privacy_policy_slug(self):
        app = self.create_app()
        data = self.base_data()
        self.client.put(self.get_url, data=json.dumps(data))
        url = reverse('app-privacy-policy-detail', kwargs={'pk': app.app_slug})
        res = self.client.get(url)
        eq_(res.json['privacy_policy'], data['privacy_policy'])

    def base_data(self):
        return {'support_email': 'a@a.com',
                'privacy_policy': 'wat',
                'homepage': 'http://www.whatever.com',
                'name': 'mozball',
                'categories': [c.slug for c in self.categories],
                'description': 'wat...',
                'premium_type': 'free',
                'regions': ['us'],
                'device_types': amo.DEVICE_LOOKUP.keys()}

    def test_put(self):
        app = self.create_app()
        res = self.client.put(self.get_url, data=json.dumps(self.base_data()))
        eq_(res.status_code, 202)
        app = Webapp.objects.get(pk=app.pk)
        eq_(app.privacy_policy, 'wat')

    def test_put_as_post(self):
        # This is really a test of the HTTP_X_HTTP_METHOD_OVERRIDE header
        # and that signing works correctly. Do a POST, but ask tastypie to do
        # a PUT.
        self.create_app()
        res = self.client.post(self.get_url, data=json.dumps(self.base_data()),
                               HTTP_X_HTTP_METHOD_OVERRIDE='PUT')
        eq_(res.status_code, 202)

    def test_put_anon(self):
        app = self.create_app()
        app.update(status=amo.STATUS_PUBLIC)
        res = self.anon.put(self.get_url, data=json.dumps(self.base_data()))
        eq_(res.status_code, 403)

    def test_put_categories_worked(self):
        app = self.create_app()
        res = self.client.put(self.get_url, data=json.dumps(self.base_data()))
        eq_(res.status_code, 202)
        app = Webapp.objects.get(pk=app.pk)
        eq_(set([c.pk for c in app.categories.all()]),
            set([c.pk for c in self.categories]))

    def test_get_content_ratings(self):
        rating = ratingsbodies.CLASSIND_12
        app = self.create_app()
        app.content_ratings.create(ratings_body=ratingsbodies.CLASSIND.id,
                                   rating=rating.id)
        app.save()

        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        cr = data.get('content_ratings')['ratings']

        self.assertIn('br', cr.keys())
        eq_(cr['br']['body'], 'CLASSIND')
        eq_(cr['br']['rating'], rating.name)
        eq_(cr['br']['description'], unicode(rating.description))

    def test_get_content_descriptors(self):
        app = self.create_app()
        app.set_descriptors(['has_esrb_blood', 'has_pegi_scary'])

        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(data['content_ratings']['descriptors'],
            [{'label': 'esrb-blood', 'name': 'Blood', 'ratings_body': 'esrb'},
             {'label': 'pegi-scary', 'name': 'Fear', 'ratings_body': 'pegi'}])

    def test_get_interactive_elements(self):
        app = self.create_app()
        app.set_interactives(['has_social_networking', 'has_shares_info'])

        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)

        eq_(data['content_ratings']['interactive_elements'],
            [{'label': 'shares-info', 'name': 'Shares Info'},
             {'label': 'social-networking', 'name': 'Social Networking'}])

    def test_post_content_ratings(self):
        """Test the @action on AppViewSet to attach the content ratings."""
        app = self.create_app()
        url = reverse('app-content-ratings', kwargs={'pk': app.pk})
        res = self.client.post(url, data=json.dumps(
            {'submission_id': 50, 'security_code': 'AB12CD3'}))
        eq_(res.status_code, 204)
        eq_(res.content, '')

    def test_post_content_ratings_bad(self):
        """Test the @action on AppViewSet to attach the content ratings."""
        app = self.create_app()
        url = reverse('app-content-ratings', kwargs={'pk': app.pk})
        # Missing `security_code`.
        res = self.client.post(url, data=json.dumps({'submission_id': 50}))
        eq_(res.status_code, 400)
        eq_(json.loads(res.content),
            {'security_code': ['This field is required.']})

    def test_dehydrate(self):
        app = self.create_app()
        res = self.client.put(self.get_url, data=json.dumps(self.base_data()))
        eq_(res.status_code, 202)
        res = self.client.get(self.get_url + '?lang=en')
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        self.assertSetEqual(data['categories'],
                            [c.slug for c in self.categories])
        eq_(data['current_version'], app.current_version.version)
        self.assertSetEqual(data['device_types'],
                            [n.api_name for n in amo.DEVICE_TYPES.values()])
        eq_(data['homepage'], u'http://www.whatever.com')
        eq_(data['is_packaged'], False)
        eq_(data['author'], 'Mozilla Labs')
        eq_(data['manifest_url'], app.manifest_url)
        eq_(data['premium_type'], 'free')
        eq_(data['price'], None)
        eq_(data['price_locale'], None)
        eq_(data['public_stats'], False)
        eq_(data['support_email'], u'a@a.com')
        eq_(data['ratings'], {'count': 0, 'average': 0.0})
        eq_(data['user'], {'developed': True, 'installed': False,
                           'purchased': False})

    def test_ratings(self):
        app = self.create_app()
        rater = UserProfile.objects.get(pk=999)
        Review.objects.create(addon=app, user=self.user, body='yes', rating=3)
        Review.objects.create(addon=app, user=rater, body='no', rating=2)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['ratings'], {'count': 2, 'average': 2.5})

    def test_put_wrong_category(self):
        self.create_app()
        wrong = Category.objects.create(name='wrong', slug='wrong',
                                        type=amo.ADDON_EXTENSION,
                                        application_id=amo.FIREFOX.id)
        data = self.base_data()
        data['categories'] = [wrong.slug]
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 400)
        assert 'does not exist' in res.json['categories'][0]

    def test_put_no_categories(self):
        self.create_app()
        data = self.base_data()
        del data['categories']
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 400)
        eq_(res.json['categories'], ['This field is required.'])

    def test_put_no_desktop(self):
        self.create_app()
        data = self.base_data()
        del data['device_types']
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 400)
        eq_(res.json['device_types'], ['This field is required.'])

    def test_put_devices_worked(self):
        app = self.create_app()
        data = self.base_data()
        data['device_types'] = [a.api_name for a in amo.DEVICE_TYPES.values()]
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 202)
        app = Webapp.objects.get(pk=app.pk)
        eq_(set(d for d in app.device_types),
            set(amo.DEVICE_TYPES[d] for d in amo.DEVICE_TYPES.keys()))

    def test_put_desktop_error_nice(self):
        self.create_app()
        data = self.base_data()
        data['device_types'] = [12345]
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 400)
        assert '12345' in res.json['device_types'][0], res.data

    def create_price(self, price):
        tier = Price.objects.create(price=price)
        # This is needed for the serialisation of the app.
        PriceCurrency.objects.create(tier=tier, price=price, provider=1,
                                     region=regions.US.id)

    def test_put_price(self):
        app = self.create_app()
        data = self.base_data()
        self.create_price('1.07')
        data['premium_type'] = 'premium'
        data['price'] = '1.07'
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 202)
        eq_(str(app.reload().get_price(region=regions.US.id)), '1.07')

    def test_put_premium_inapp(self):
        app = self.create_app()
        data = self.base_data()
        self.create_price('1.07')
        data['premium_type'] = 'premium-inapp'
        data['price'] = '1.07'
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 202)
        app = app.reload()
        eq_(str(app.get_price(region=regions.US.id)), '1.07')
        eq_(app.premium_type, amo.ADDON_PREMIUM_INAPP)

    def test_put_bad_price(self):
        self.create_app()
        data = self.base_data()
        self.create_price('1.07')
        self.create_price('3.14')
        data['premium_type'] = 'premium'
        data['price'] = "2.03"
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 400)
        eq_(res.json['price'][0],
            'Premium app specified without a valid price. Price can be one of '
            '"1.07", "3.14".')

    def test_put_no_price(self):
        self.create_app()
        data = self.base_data()
        Price.objects.create(price='1.07')
        Price.objects.create(price='3.14')
        data['premium_type'] = 'premium'
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 400)
        eq_(res.json['price'][0],
            'Premium app specified without a valid price. Price can be one of '
            '"1.07", "3.14".')

    def test_put_free_inapp(self):
        app = self.create_app()
        data = self.base_data()
        data['premium_type'] = 'free-inapp'
        res = self.client.put(self.get_url, data=json.dumps(data))
        eq_(res.status_code, 202)
        eq_(app.reload().get_price(region=regions.US.id), None)

# TODO: renable when regions are sorted out.
#    def test_put_region_bad(self):
#        self.create_app()
#        data = self.base_data()
#        data['regions'] = []
#        res = self.client.put(self.get_url, data=json.dumps(data))
#        eq_(res.status_code, 400)
#
#    def test_put_region_good(self):
#        app = self.create_app()
#        data = self.base_data()
#        data['regions'] = ['br', 'us', 'uk']
#        res = self.client.put(self.get_url, data=json.dumps(data))
#        eq_(res.status_code, 202)
#        eq_(app.get_regions(), [regions.BR, regions.UK, regions.US])

    def test_put_not_mine(self):
        obj = self.create_app()
        obj.authors.clear()
        res = self.client.put(self.get_url, data='{}')
        eq_(res.status_code, 403)

    def test_put_not_there(self):
        url = reverse('app-detail', kwargs={'pk': 123})
        res = self.client.put(url, data='{}')
        eq_(res.status_code, 404)

    def test_delete(self):
        obj = self.create_app()
        res = self.client.delete(self.get_url)
        eq_(res.status_code, 204)
        assert not Webapp.objects.filter(pk=obj.pk).exists()

    def test_delete_not_mine(self):
        obj = self.create_app()
        obj.authors.clear()
        res = self.client.delete(self.get_url)
        eq_(res.status_code, 403)
        assert Webapp.objects.filter(pk=obj.pk).exists()

    def test_reviewer_get(self):
        self.create_app()
        editor = UserProfile.objects.get(email='admin@mozilla.com')
        g = Group.objects.create(rules='Apps:Review,Reviews:Edit')
        GroupUser.objects.create(group=g, user=editor)
        ac = Access.objects.create(key='adminOauthKey', secret=generate(),
                                   user=editor.user)
        client = RestOAuthClient(ac)
        r = client.get(self.get_url)
        eq_(r.status_code, 200)

    def test_admin_get(self):
        self.create_app()
        admin = UserProfile.objects.get(email='admin@mozilla.com')
        g = Group.objects.create(rules='*:*')
        GroupUser.objects.create(group=g, user=admin)
        ac = Access.objects.create(key='adminOauthKey', secret=generate(),
                                   user=admin.user)
        client = RestOAuthClient(ac)
        r = client.get(self.get_url)
        eq_(r.status_code, 200)


class CreatePackagedHandler(amo.tests.AMOPaths, RestOAuth):
    fixtures = fixture('user_2519', 'platform_all')

    def setUp(self):
        super(CreatePackagedHandler, self).setUp()
        self.list_url = reverse('app-list')
        self.user = UserProfile.objects.get(pk=2519)
        self.file = tempfile.NamedTemporaryFile('w', suffix='.zip').name
        self.packaged_copy_over(self.file, 'mozball.zip')
        self.categories = []
        for x in range(0, 2):
            self.categories.append(Category.objects.create(
                name='cat-%s' % x,
                type=amo.ADDON_WEBAPP))

    def create(self):
        return FileUpload.objects.create(user=self.user, path=self.file,
                                         name=self.file, valid=True)


@patch('versions.models.Version.is_privileged', False)
class TestPackagedAppCreateHandler(CreatePackagedHandler):
    fixtures = fixture('user_2519', 'platform_all')

    def test_create(self):
        obj = self.create()
        res = self.client.post(self.list_url,
                               data=json.dumps({'upload': obj.uuid}))
        eq_(res.status_code, 201)
        content = json.loads(res.content)
        eq_(content['status'], 0)

        # Note the packaged status is not returned in the result.
        app = Webapp.objects.get(app_slug=content['slug'])
        eq_(app.is_packaged, True)


class TestListHandler(CreateHandler, AMOPaths):
    fixtures = fixture('user_2519', 'user_999', 'platform_all')

    def create(self, users):
        app = Addon.objects.create(type=amo.ADDON_WEBAPP)
        for user in users:
            AddonUser.objects.create(user=user, addon=app)
        return app

    def create_apps(self, *all_owners):
        apps = []
        for owners in all_owners:
            owners = [UserProfile.objects.get(pk=pk) for pk in owners]
            apps.append(self.create(owners))

        return apps

    def test_create(self):
        apps = self.create_apps([2519], [999])
        res = self.client.get(self.list_url)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['id'], apps[0].pk)

    def test_multiple(self):
        apps = self.create_apps([2519], [999, 2519])
        res = self.client.get(self.list_url)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 2)
        pks = set([data['objects'][0]['id'], data['objects'][1]['id']])
        eq_(pks, set([app.pk for app in apps]))

    def test_lang(self):
        app = app_factory(description={'fr': 'Le blah', 'en-US': 'Blah'})
        url = reverse('app-detail', args=[app.pk])

        res = self.client.get(url + '?lang=en')
        eq_(json.loads(res.content)['description'], 'Blah')

        res = self.client.get(url + '?lang=fr')
        eq_(json.loads(res.content)['description'], 'Le blah')


class TestAppDetail(RestOAuth):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self, api_name='apps'):
        super(TestAppDetail, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.get_url = reverse('app-detail', kwargs={'pk': self.app.app_slug})

    def test_price(self):
        res = self.client.get(self.get_url)
        data = json.loads(res.content)
        eq_(data['price'], None)

    def test_price_other_region(self):
        res = self.client.get(self.get_url, {'lang': 'fr'})
        data = json.loads(res.content)
        eq_(data['price'], None)

    def test_nonexistent_app(self):
        """
        In combination with test_nonregion, this ensures that a distinction is
        appropriately drawn between attempts to access nonexistent apps and
        attempts to access apps that are unavailable due to legal restrictions.
        """
        url = reverse('app-detail', kwargs={'pk': 1})
        res = self.client.get(url)
        eq_(res.status_code, 404)

    def test_nonregion(self):
        self.app.addonexcludedregion.create(region=regions.BR.id)
        self.app.support_url = u'http://www.example.com/fake_support_url'
        self.app.save()
        res = self.client.get(self.get_url, data={'region': 'br'})
        eq_(res.status_code, 451)
        data = json.loads(res.content)['detail']
        eq_(data['reason'], 'Not available in your region.')
        eq_(data['support_email'], '')
        eq_(data['support_url'], 'http://www.example.com/fake_support_url')

    def test_owner_nonregion(self):
        AddonUser.objects.create(addon_id=337141, user_id=self.user.pk)
        AddonExcludedRegion.objects.create(addon_id=337141,
                                           region=regions.BR.id)
        res = self.client.get(self.get_url, data={'region': 'br'})
        eq_(res.status_code, 200)

    def test_packaged_manifest_url(self):
        self.app.update(is_packaged=True)
        res = self.client.get(self.get_url, pk=self.app.app_slug)
        data = json.loads(res.content)
        eq_(self.app.get_manifest_url(), data['manifest_url'])

    def test_user_info_with_shared_secret(self):
        def fakeauth(auth, req, **kw):
            req.amo_user = UserProfile.objects.get(id=self.user.pk)
            req.user = self.user
            return True
        with patch('mkt.api.authentication.RestSharedSecretAuthentication'
                   '.is_authenticated', fakeauth):
            res = self.anon.get(self.get_url)
        assert 'user' in res.json

    def test_get_upsold(self):
        free = Webapp.objects.create(status=amo.STATUS_PUBLIC)
        AddonUpsell.objects.create(premium_id=337141, free=free)
        res = self.client.get(self.get_url)
        eq_(res.json['upsold'],
            reverse('app-detail', kwargs={'pk': free.pk}))

    def test_tags(self):
        tag1 = Tag.objects.create(tag_text='example1')
        tag2 = Tag.objects.create(tag_text='example2')
        AddonTag.objects.create(tag=tag1, addon=self.app)
        AddonTag.objects.create(tag=tag2, addon=self.app)
        res = self.client.get(self.get_url, pk=self.app.app_slug)
        data = json.loads(res.content)
        eq_(data['tags'], ['example1', 'example2'])


class TestCategoryHandler(RestOAuth):

    def setUp(self):
        super(TestCategoryHandler, self).setUp()
        self.cat = Category.objects.create(name='Webapp',
                                           type=amo.ADDON_WEBAPP,
                                           slug='thewebapp')
        self.cat.name = {'fr': 'Le Webapp'}
        self.cat.save()
        self.other = Category.objects.create(name='other',
                                             type=amo.ADDON_EXTENSION)

        self.list_url = reverse('app-category-list')
        self.get_url = reverse('app-category-detail',
                               kwargs={'pk': self.cat.pk})

    def test_verbs(self):
        self._allowed_verbs(self.list_url, ['get'])
        self._allowed_verbs(self.get_url, ['get'])

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.list_url), 'get')

    def test_weight(self):
        self.cat.update(weight=-1)
        res = self.anon.get(self.list_url)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 0)

    def test_get_slug(self):
        url = reverse('app-category-detail', kwargs={'pk': self.cat.slug})
        res = self.client.get(url)
        data = json.loads(res.content)
        eq_(data['id'], self.cat.pk)

    def test_get_categories(self):
        res = self.anon.get(self.list_url)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['name'], 'Webapp')
        eq_(data['objects'][0]['slug'], 'thewebapp')

    def test_get_category(self):
        res = self.anon.get(self.get_url)
        data = json.loads(res.content)
        eq_(data['name'], 'Webapp')

    def test_get_category_localised(self):
        res = self.anon.get(self.get_url, HTTP_ACCEPT_LANGUAGE='fr')
        data = json.loads(res.content)
        eq_(data['name'], 'Le Webapp')

        res = self.anon.get(self.get_url, HTTP_ACCEPT_LANGUAGE='en-US')
        data = json.loads(res.content)
        eq_(data['name'], 'Webapp')

    def test_get_other_category(self):
        res = self.anon.get(reverse('app-category-detail',
                                    kwargs={'pk': self.other.pk}))
        eq_(res.status_code, 404)


class TestErrorReporter(RestOAuth):
    @patch('django.conf.settings.SENTRY_DSN', 'FAKE_DSN')
    @patch('raven.base.Client')
    def test_report_stack(self, Client):
        msg = u'a log message'
        stack = {u'foo': u'frame 1', u'baz': u'frame 2'}
        res = self.anon.post(
            reverse('error-reporter'),
            data=json.dumps([{'stacktrace': {'frames': stack}, 'value': msg}]))
        eq_(res.status_code, 204)
        Client().capture.assert_called_with(
            'raven.events.Exception', data=[{u'stacktrace': {u'frames': stack},
                                             u'value': msg}])

MANIFEST = """
   {"name": "Steamcubev2!",
    "icons": {"128": "http://testmanifest.com/icon-128.png",
              "48": "http://testmanifest.com/icon-48.png",
              "16": "http://testmanifest.com/icon-16.png"},
    "installs_allowed_from": ["*"],
    "description":
    "This app has been automatically generated by testmanifest.com",
    "version": "1.0",
    "developer": {"url": "http://mozilla.com", "name": "Mozilla Marketplace"}}
"""


@patch('mkt.developers.tasks._fetch_content')
@patch('mkt.webapps.tasks.validator')
class TestRefreshManifest(RestOAuth):
    fixtures = fixture('user_2519', 'webapp_337141', 'platform_all')

    def setUp(self):
        super(TestRefreshManifest, self).setUp()
        self.url = reverse('app-refresh-manifest-detail',
                           kwargs={'pk': 337141})

    def test_anon(self, validator, fetch):
        res = self.anon.post(self.url)
        eq_(res.status_code, 403)
        assert not fetch.called

    def test_non_owner(self, validator, fetch):
        res = self.client.post(self.url)
        eq_(res.status_code, 403)
        assert not fetch.called

    def test_refresh(self, validator, fetch):
        validator.side_effect = lambda pk: setattr(
            FileUpload.objects.get(pk=pk), 'validation',
            json.dumps({'success': True, 'messages': []}))
        content = StringIO(MANIFEST)
        content.headers = {
            'Content-Type': 'application/x-web-app-manifest+json'}
        fetch.return_value = content
        AddonUser.objects.create(addon_id=337141, user_id=self.user.pk)
        res = self.client.post(self.url)
        eq_(res.status_code, 204)
        assert fetch.called

    def test_failed_refresh(self, validator, fetch):
        fetch.side_effect = Exception
        AddonUser.objects.create(addon_id=337141, user_id=self.user.pk)
        res = self.client.post(self.url)
        eq_(res.status_code, 204)
        assert fetch.called
        assert not validator.called

    def test_no_packaged(self, validator, fetch):
        AddonUser.objects.create(addon_id=337141, user_id=self.user.pk)
        Webapp.objects.filter(pk=337141).update(is_packaged=True)
        res = self.client.post(self.url)
        eq_(res.status_code, 400)
        eq_(res.json, {'reason': 'App is a packaged app.'})


class TestPriceTier(RestOAuth):
    fixtures = ['data/user_2519', 'data/admin', 'market/prices']

    def setUp(self):
        self.permission = 'Prices:Edit'
        RestOAuth.setUp(self)
        self.list_url = reverse('price-tier-list')
        self.detail_url = reverse('price-tier-detail', kwargs={'pk': 1})

    def test_list(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.get(self.list_url)
        j = json.loads(res.content)
        eq_(len(j['objects']), 2)
        eq_(j['objects'][0], {
            'active': True,
            'name': '1',
            'price': '0.99',
            'method': 'operator+card',
            'resource_uri': self.detail_url
            })

    def test_detail(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.get(self.detail_url)
        j = json.loads(res.content)
        eq_(j, {
            'active': True,
            'name': '1',
            'price': '0.99',
            'method': 'operator+card',
            'resource_uri': self.detail_url
            })

    def test_post_unauthorized(self):
        res = self.client.post(self.list_url, '{}')
        eq_(res.status_code, 403)

    def test_post_admin(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.post(
            self.list_url,
            json.dumps({'name': '3',
                        'price': '3.14',
                        'method': 'operator+card',
                        'active': True}))
        eq_(res.status_code, 201)
        p = Price.objects.get(pk=3)
        eq_(p.name, '3')
        eq_(p.price, Decimal('3.14'))
        eq_(p.method, amo.PAYMENT_METHOD_ALL)
        assert p.active

    def test_put_unauthorized(self):
        res = self.client.put(self.detail_url, '{}')
        eq_(res.status_code, 403)

    def test_put(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.put(
            self.detail_url,
            json.dumps({'name': '1',
                        'price': '0.10',
                        'method': 'operator',
                        'active': True}))
        eq_(res.status_code, 200)
        p = Price.objects.get(pk=1)
        eq_(p.name, '1')
        eq_(p.price, Decimal('0.10'))
        eq_(p.method, amo.PAYMENT_METHOD_OPERATOR)
        assert p.active

    def test_delete_unauthorized(self):
        res = self.client.delete(self.detail_url)
        eq_(res.status_code, 403)

    def test_delete(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.delete(self.detail_url)
        eq_(res.status_code, 204)
        assert not Price.objects.filter(pk=1).exists()


class TestPriceCurrency(RestOAuth):
    fixtures = ['data/user_2519', 'data/admin', 'market/prices']

    def setUp(self):
        self.permission = 'Prices:Edit'
        RestOAuth.setUp(self)
        self.list_url = reverse('price-currency-list')
        self.detail_url = reverse('price-currency-detail', kwargs={'pk': 1})
        self.tier_url = reverse('price-tier-detail', kwargs={'pk': 1})

    def test_list(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.get(self.list_url)
        j = json.loads(res.content)
        eq_(len(j['objects']), 6)
        eq_(j['objects'][0], {
            'carrier': None,
            'currency': 'PLN',
            'method': 'operator+card',
            'price': '5.01',
            'provider': 'bango',
            'resource_uri': self.detail_url,
            'tier': self.tier_url})

    def test_detail(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.get(self.detail_url)
        j = json.loads(res.content)
        eq_(j, {
            'carrier': None,
            'currency': 'PLN',
            'method': 'operator+card',
            'price': '5.01',
            'provider': 'bango',
            'resource_uri': self.detail_url,
            'tier': self.tier_url
        })

    def test_post_unauthorized(self):
        res = self.client.post(self.list_url, '{}')
        eq_(res.status_code, 403)

    def test_post_admin(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.post(
            self.list_url,
            json.dumps({
                'tier': self.tier_url,
                'carrier': None,
                'currency': 'PHP',
                'method': 'operator',
                'price': '10.05',
                'provider': 'bango'}))
        eq_(res.status_code, 201)
        # Get the pk from the response.
        pk = res.json['resource_uri'].split('/')[-2]
        p = PriceCurrency.objects.get(pk=pk)
        eq_(p.tier_id, 1)
        eq_(p.price, Decimal('10.05'))
        eq_(p.method, amo.PAYMENT_METHOD_OPERATOR)
        eq_(p.currency, 'PHP')

    def test_put_unauthorized(self):
        res = self.client.put(self.detail_url, '{}')
        eq_(res.status_code, 403)

    def test_put(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.put(
            self.detail_url,
            json.dumps({
                'tier': self.tier_url,
                'carrier': None,
                'currency': 'PHP',
                'method': 'operator',
                'price': '10.05',
                'provider': 'bango'}))
        eq_(res.status_code, 200)
        p = PriceCurrency.objects.get(pk=1)
        eq_(p.tier_id, 1)
        eq_(p.price, Decimal('10.05'))
        eq_(p.method, amo.PAYMENT_METHOD_OPERATOR)
        eq_(p.currency, 'PHP')

    def test_delete_unauthorized(self):
        res = self.client.delete(self.detail_url)
        eq_(res.status_code, 403)

    def test_delete(self):
        self.grant_permission(self.profile, self.permission)
        res = self.client.delete(self.detail_url)
        eq_(res.status_code, 204)
        assert not PriceCurrency.objects.filter(pk=1).exists()


class TestLargeTextField(TestCase):
    fixtures = fixture('webapp_337141')

    def test_receive(self):
        data = 'privacy policy text'
        into = {}
        field = LargeTextField(view_name='app-privacy-policy-detail')
        field.field_from_native({'field_name': data}, None, 'field_name', into)
        eq_(into['field_name'], data)

    def test_send(self):
        app = Webapp.objects.get(pk=337141)
        app.privacy_policy = 'privacy policy text'
        field = LargeTextField(view_name='app-privacy-policy-detail')
        field.context = {'request': None}
        url = field.field_to_native(app, None)
        self.assertApiUrlEqual(url, '/apps/app/337141/privacy/')
