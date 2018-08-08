# -*- coding: utf-8 -*-
from django.test import override_settings

from mock import Mock
from rest_framework.test import APIRequestFactory

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.ratings.models import Rating
from olympia.ratings.serializers import RatingSerializer


class TestBaseRatingSerializer(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.view = Mock(spec=['get_addon_object'])
        self.user = user_factory()

    def serialize(self, **extra_context):
        context = {
            'request': self.request,
            'view': self.view,
        }
        context.update(extra_context)
        serializer = RatingSerializer(context=context)
        return serializer.to_representation(self.rating)

    def test_basic(self):
        addon = addon_factory()
        self.view.get_addon_object.return_value = addon
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')

        result = self.serialize()

        assert result['id'] == self.rating.pk
        assert result['addon'] == {
            'id': addon.pk,
            'slug': addon.slug,
        }
        assert result['body'] == unicode(self.rating.body)
        assert result['created'] == (
            self.rating.created.replace(microsecond=0).isoformat() + 'Z')
        assert result['previous_count'] == int(self.rating.previous_count)
        assert result['is_developer_reply'] is False
        assert result['is_latest'] == self.rating.is_latest
        assert result['score'] == int(self.rating.rating)
        assert result['reply'] is None
        assert result['user'] == {
            'id': self.user.pk,
            'name': unicode(self.user.name),
            'url': None,
            'username': self.user.username,
        }
        assert result['version'] == {
            'id': self.rating.version.id,
            'version': self.rating.version.version
        }

        self.rating.update(version=None)
        result = self.serialize()
        assert result['version'] is None
        # Check the default, when DRF_API_GATES['ratings-title-shim'] isn't set
        assert 'title' not in result

    @override_settings(DRF_API_GATES={None: ('ratings-rating-shim',)})
    def test_ratings_score_is_rating_with_gate(self):
        addon = addon_factory()
        self.view.get_addon_object.return_value = addon
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')

        result = self.serialize()

        assert result['id'] == self.rating.pk
        assert result['rating'] == int(self.rating.rating)

    @override_settings(DRF_API_GATES={None: ('ratings-title-shim',)})
    def test_ratings_title_is_returned_with_gate(self):
        addon = addon_factory()
        self.view.get_addon_object.return_value = addon
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')

        result = self.serialize()

        assert result['id'] == self.rating.pk
        assert 'title' in result
        assert result['title'] is None

    def test_url_for_yourself(self):
        addon = addon_factory()
        self.view.get_addon_object.return_value = addon
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')
        # should include the account profile for your own requests
        self.request.user = self.user
        result = self.serialize()
        assert result['user']['url'] == absolutify(self.user.get_url_path())

    def test_url_for_admins(self):
        addon = addon_factory()
        self.view.get_addon_object.return_value = addon
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')
        # should include account profile url for admins
        admin = user_factory()
        self.grant_permission(admin, 'Users:Edit')
        self.request.user = admin
        result = self.serialize()
        assert result['user']['url'] == absolutify(self.user.get_url_path())

    def test_addon_slug_even_if_view_doesnt_return_addon_object(self):
        addon = addon_factory()
        self.view.get_addon_object.return_value = None
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')

        result = self.serialize()

        assert result['id'] == self.rating.pk
        assert result['addon'] == {
            'id': addon.pk,
            'slug': addon.slug,
        }

    def test_with_previous_count(self):
        addon = addon_factory()
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?')
        self.rating.update(is_latest=False, previous_count=42)
        result = self.serialize()

        assert result['id'] == self.rating.pk
        assert result['previous_count'] == 42
        assert result['is_latest'] is False

    def test_with_reply(self):
        def _test_reply(data):
            assert data['id'] == reply.pk
            assert data['body'] == unicode(reply.body)
            assert data['created'] == (
                reply.created.replace(microsecond=0).isoformat() + 'Z')
            assert data['is_developer_reply'] is True
            assert data['user'] == {
                'id': reply_user.pk,
                'name': unicode(reply_user.name),
                # should be the profile for a developer
                'url': absolutify(reply_user.get_url_path()),
                'username': reply_user.username,
            }

        reply_user = user_factory()
        addon = addon_factory(users=[reply_user])
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, version=addon.current_version,
            body=u'This is my rëview. Like ît ?')
        reply = Rating.objects.create(
            addon=addon, user=reply_user, version=addon.current_version,
            body=u'Thîs is a reply.', reply_to=self.rating)

        result = self.serialize()

        assert result['reply']
        assert 'score' not in result['reply']
        assert 'reply' not in result['reply']
        _test_reply(result['reply'])

        # If we instantiate a standard RatingSerializer class with a reply, it
        # should work like normal. `score` and `reply` should be there, blank.
        self.rating = reply
        result = self.serialize()
        _test_reply(result)
        assert result['score'] is None
        assert result['reply'] is None

    def test_reply_profile_url_for_yourself(self):
        addon = addon_factory()
        reply_user = user_factory()
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, version=addon.current_version,
            body=u'This is my rëview. Like ît ?')
        Rating.objects.create(
            addon=addon, user=reply_user, version=addon.current_version,
            body=u'Thîs is a reply.', reply_to=self.rating)
        # should be the profile for your own requests
        self.request.user = reply_user
        result = self.serialize()
        assert result['reply']['user']['url'] == absolutify(
            reply_user.get_url_path())

    def test_with_deleted_reply(self):
        addon = addon_factory()
        reply_user = user_factory()
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, version=addon.current_version,
            body=u'This is my rëview. Like ît ?')
        reply = Rating.objects.create(
            addon=addon, user=reply_user, version=addon.current_version,
            body=u'Thîs is a reply.', reply_to=self.rating)
        reply.delete()

        result = self.serialize()

        assert result['reply'] is None

    def test_with_deleted_reply_but_view_allowing_it_to_be_shown(self):
        reply_user = user_factory()
        addon = addon_factory(users=[reply_user])
        self.view.get_addon_object.return_value = addon
        self.view.should_access_deleted_reviews = True
        self.rating = Rating.objects.create(
            addon=addon, user=self.user, version=addon.current_version,
            body=u'This is my rëview. Like ît ?')
        reply = Rating.objects.create(
            addon=addon, user=reply_user, version=addon.current_version,
            body=u'Thîs is a reply.', reply_to=self.rating)

        result = self.serialize()

        assert result['reply']
        assert 'rating' not in result['reply']
        assert 'reply' not in result['reply']
        assert result['reply']['id'] == reply.pk
        assert result['reply']['body'] == unicode(reply.body)
        assert result['reply']['created'] == (
            reply.created.replace(microsecond=0).isoformat() + 'Z')
        assert result['reply']['user'] == {
            'id': reply_user.pk,
            'name': unicode(reply_user.name),
            'url': absolutify(reply_user.get_url_path()),
            'username': reply_user.username,
        }

    def test_readonly_fields(self):
        serializer = RatingSerializer(context={'request': self.request})
        assert serializer.fields['created'].read_only is True
        assert serializer.fields['id'].read_only is True
        assert serializer.fields['reply'].read_only is True
        assert serializer.fields['user'].read_only is True
