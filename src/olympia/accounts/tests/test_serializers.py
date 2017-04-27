# -*- coding: utf-8 -*-
from olympia import amo
from olympia.amo.tests import (
    addon_factory, BaseTestCase, collection_factory, days_ago, user_factory)
from olympia.accounts.serializers import (
    PublicUserProfileSerializer, UserProfileSerializer)
from olympia.reviews.models import Review


class TestPublicUserProfileSerializer(BaseTestCase):
    serializer = PublicUserProfileSerializer
    user_kwargs = {
        'username': 'amo', 'averagerating': 3.6,
        'biography': 'stuff', 'homepage': 'http://mozilla.org/',
        'location': 'everywhere', 'occupation': 'job'}

    def setUp(self):
        self.user = user_factory(**self.user_kwargs)

    def serialize(self):
        return self.serializer(self.user).data

    def test_picture_url(self):
        serial = self.serialize()
        assert ('anon_user.png' in serial['picture_url'])
        assert serial['picture_type'] == ''

    def test_basic(self):
        data = self.serialize()
        for prop, val in self.user_kwargs.items():
            assert data[prop] == unicode(val), prop
        return data

    def test_addons(self):
        del self.user.addons_listed
        assert len(self.serialize()['addons']) == 0

        addon_factory(users=[self.user])
        addon_factory(users=[self.user])
        addon_factory(status=amo.STATUS_NULL, users=[self.user])
        del self.user.addons_listed
        assert len(self.serialize()['addons']) == 2  # only public addons.

    def test_reviews(self):
        addon = addon_factory()
        Review.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')
        addon = addon_factory()
        Review.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')
        self.user = self.user.reload()
        assert len(self.serialize()['reviews']) == 2


class TestUserProfileSerializer(TestPublicUserProfileSerializer):
    serializer = UserProfileSerializer

    def setUp(self):
        self.now = days_ago(0)
        self.user_kwargs.update({
            'email': u'a@m.o',
            'display_name': u'This is my náme',
            'last_login_ip': '123.45.67.89',
        })
        super(TestUserProfileSerializer, self).setUp()

    def test_collections(self):
        collection_factory(author=self.user)
        collection_factory(author=self.user)
        assert len(self.serialize()['collections']) == 2

    def test_basic(self):
        # Have to update these separately as dates as tricky.  As are bools.
        self.user.update(last_login=self.now, read_dev_agreement=self.now,
                         is_verified=True)
        data = super(TestUserProfileSerializer, self).test_basic()
        assert data['is_verified'] is True
        assert data['last_login'] == (
            self.now.replace(microsecond=0).isoformat() + 'Z')
        assert data['read_dev_agreement'] == data['last_login']
