# -*- coding: utf-8 -*-
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.activity.serializers import ActivityLogSerializer
from olympia.amo.helpers import absolutify
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory)


class LogMixin(object):
    def log(self, comments, action, created):
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

    def serialize(self, id_):
        serializer = ActivityLogSerializer(context={'request': self.request})
        return serializer.to_representation(id_)

    def test_basic(self):
        now = self.days_ago(0)
        entry = self.log(u'Oh nôes!', amo.LOG.REJECT_VERSION, now)

        result = self.serialize(entry)

        assert result['id'] == entry.pk
        assert result['date'] == now.isoformat()
        assert result['action'] == 'rejected'
        assert result['action_label'] == 'Rejected'
        assert result['comments'] == u'Oh nôes!'
        assert result['user'] == {
            'name': self.user.name,
            'url': absolutify(self.user.get_url_path())}
