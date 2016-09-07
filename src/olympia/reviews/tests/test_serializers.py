# -*- coding: utf-8 -*-
from mock import Mock
from rest_framework.test import APIRequestFactory

from olympia.amo.helpers import absolutify
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.reviews.models import Review
from olympia.reviews.serializers import ReviewSerializer


class TestBaseReviewSerializer(TestCase):
    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.user = user_factory()

    def serialize(self, **extra_context):
        context = {'request': self.request, 'view': Mock(spec=[])}
        context.update(extra_context)
        serializer = ReviewSerializer(context=context)
        return serializer.to_representation(self.review)

    def test_basic(self):
        addon = addon_factory()
        self.review = Review.objects.create(
            addon=addon, user=self.user, rating=4,
            version=addon.current_version, body=u'This is my rëview. Like ît?',
            title=u'My Review Titlé')
        result = self.serialize()

        assert result['id'] == self.review.pk
        assert result['body'] == unicode(self.review.body)
        assert result['created'] == self.review.created.isoformat()
        assert result['title'] == unicode(self.review.title)
        assert result['rating'] == int(self.review.rating)
        assert result['reply'] is None
        assert result['user'] == {
            'name': unicode(self.user.name),
            'url': absolutify(self.user.get_url_path()),
        }
        assert result['version'] == self.review.version.version

        self.review.update(version=None)
        result = self.serialize()
        assert result['version'] is None

    def test_with_reply(self):
        addon = addon_factory()
        reply_user = user_factory()
        self.review = Review.objects.create(
            addon=addon, user=self.user, version=addon.current_version,
            body=u'This is my rëview. Like ît ?', title=u'My Review Titlé')
        reply = Review.objects.create(
            addon=addon, user=reply_user, version=addon.current_version,
            body=u'Thîs is a reply.', title=u'My rèply', reply_to=self.review)

        result = self.serialize()

        assert result['reply']
        assert 'rating' not in result['reply']
        assert 'reply' not in result['reply']
        assert result['reply']['id'] == reply.pk
        assert result['reply']['body'] == unicode(reply.body)
        assert result['reply']['created'] == reply.created.isoformat()
        assert result['reply']['title'] == unicode(reply.title)
        assert result['reply']['user'] == {
            'name': unicode(reply_user.name),
            'url': absolutify(reply_user.get_url_path()),
        }

    def test_with_deleted_reply(self):
        addon = addon_factory()
        reply_user = user_factory()
        self.review = Review.objects.create(
            addon=addon, user=self.user, version=addon.current_version,
            body=u'This is my rëview. Like ît ?', title=u'My Review Titlé')
        reply = Review.objects.create(
            addon=addon, user=reply_user, version=addon.current_version,
            body=u'Thîs is a reply.', title=u'My rèply', reply_to=self.review)
        reply.delete()

        result = self.serialize()

        assert result['reply'] is None

    def test_with_deleted_reply_but_view_allowing_it_to_be_shown(self):
        addon = addon_factory()
        reply_user = user_factory()
        self.review = Review.objects.create(
            addon=addon, user=self.user, version=addon.current_version,
            body=u'This is my rëview. Like ît ?', title=u'My Review Titlé')
        reply = Review.objects.create(
            addon=addon, user=reply_user, version=addon.current_version,
            body=u'Thîs is a reply.', title=u'My rèply', reply_to=self.review)

        view = Mock(spec=[], should_access_deleted_reviews=True)
        view.should_access_deleted_reviews = True
        result = self.serialize(view=view)

        assert result['reply']
        assert 'rating' not in result['reply']
        assert 'reply' not in result['reply']
        assert result['reply']['id'] == reply.pk
        assert result['reply']['body'] == unicode(reply.body)
        assert result['reply']['created'] == reply.created.isoformat()
        assert result['reply']['title'] == unicode(reply.title)
        assert result['reply']['user'] == {
            'name': unicode(reply_user.name),
            'url': absolutify(reply_user.get_url_path()),
        }

    def test_readonly_fields(self):
        serializer = ReviewSerializer(context={'request': self.request})
        assert serializer.fields['created'].read_only is True
        assert serializer.fields['id'].read_only is True
        assert serializer.fields['reply'].read_only is True
        assert serializer.fields['user'].read_only is True
