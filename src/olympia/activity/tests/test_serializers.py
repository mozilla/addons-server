# -*- coding: utf-8 -*-
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.activity.serializers import ActivityLogSerializer
from olympia.amo.helpers import absolutify
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory)


class LogMixin(object):
    def log(self, comments, action, created=None):
        if not created:
            created = self.days_ago(0)
        details = {'comments': comments}
        details['version'] = self.addon.current_version.version
        kwargs = {'user': self.user, 'created': created, 'details': details}
        return amo.log(
            action, self.addon, self.addon.current_version, **kwargs)


class TestReviewNotesSerializerOutput(TestCase, LogMixin):
    def setUp(self):
        self.request = APIRequestFactory().get('/')
        self.user = user_factory()
        self.addon = addon_factory()
        self.now = self.days_ago(0)
        self.entry = self.log(u'Oh nÃ´es!', amo.LOG.REJECT_VERSION, self.now)

    def serialize(self, context=None):
        if context is None:
            context = {}
        context['request'] = self.request
        serializer = ActivityLogSerializer(context=context)
        return serializer.to_representation(self.entry)

    def test_basic(self):
        result = self.serialize()

        assert result['id'] == self.entry.pk
        assert result['date'] == self.now.isoformat()
        assert result['action'] == 'rejected'
        assert result['action_label'] == 'Rejected'
        assert result['comments'] == u'Oh nÃ´es!'
        assert result['user'] == {
            'name': self.user.name,
            'url': absolutify(self.user.get_url_path())}

    def test_should_highlight(self):
        result = self.serialize(context={'to_highlight': [self.entry]})

        assert result['id'] == self.entry.pk
        assert result['highlight']

    def test_should_not_highlight(self):
        no_highlight = self.log(u'something élse', amo.LOG.REJECT_VERSION)

        result = self.serialize(context={'to_highlight': [no_highlight]})

        assert result['id'] == self.entry.pk
        assert not result['highlight']
