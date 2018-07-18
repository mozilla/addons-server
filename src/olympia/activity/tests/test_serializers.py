# -*- coding: utf-8 -*-
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.activity.serializers import ActivityLogSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.tests import TestCase, addon_factory, user_factory


class LogMixin(object):
    def log(self, comments, action, created=None):
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED
        )
        details = {'comments': comments, 'version': version.version}
        kwargs = {'user': self.user, 'details': details}
        al = ActivityLog.create(action, self.addon, version, **kwargs)
        if created:
            al.update(created=created)
        return al


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
        assert result['date'] == self.now.isoformat() + 'Z'
        assert result['action'] == 'rejected'
        assert result['action_label'] == 'Rejected'
        assert result['comments'] == u'Oh nÃ´es!'
        assert result['user'] == {
            'id': self.user.pk,
            'name': self.user.name,
            'url': None,
            'username': self.user.username,
        }

    def test_url_for_yourself(self):
        # should include account profile url for your own requests
        self.request.user = self.user
        result = self.serialize()
        assert result['user']['url'] == absolutify(self.user.get_url_path())

    def test_url_for_developers(self):
        # should include account profile url for a developer
        addon_factory(users=[self.user])
        result = self.serialize()
        assert result['user']['url'] == absolutify(self.user.get_url_path())

    def test_url_for_admins(self):
        # should include account profile url for admins
        admin = user_factory()
        self.grant_permission(admin, 'Users:Edit')
        self.request.user = admin
        result = self.serialize()
        assert result['user']['url'] == absolutify(self.user.get_url_path())

    def test_should_highlight(self):
        result = self.serialize(context={'to_highlight': [self.entry]})

        assert result['id'] == self.entry.pk
        assert result['highlight']

    def test_should_not_highlight(self):
        no_highlight = self.log(u'something élse', amo.LOG.REJECT_VERSION)

        result = self.serialize(context={'to_highlight': [no_highlight]})

        assert result['id'] == self.entry.pk
        assert not result['highlight']

    def test_sanitized_activity_detail_not_exposed_to_developer(self):
        self.entry = self.log(u'ßäď ŞŤųƒƒ', amo.LOG.REQUEST_SUPER_REVIEW)
        result = self.serialize()

        assert result['action_label'] == amo.LOG.REQUEST_SUPER_REVIEW.short
        # Comments should be the santized text rather than the actual content.
        assert result['comments'] == amo.LOG.REQUEST_SUPER_REVIEW.sanitize
        assert result['comments'].startswith(
            'The addon has been flagged for Admin Review.'
        )

    def test_log_entry_without_details(self):
        # Create a log but without a details property.
        self.entry = ActivityLog.create(
            amo.LOG.APPROVAL_NOTES_CHANGED,
            self.addon,
            self.addon.find_latest_version(channel=amo.RELEASE_CHANNEL_LISTED),
            user=self.user,
        )
        result = self.serialize()
        # Should output an empty string.
        assert result['comments'] == ''
