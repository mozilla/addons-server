from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.activity.serializers import ActivityLogSerializer
from olympia.amo.tests import TestCase, addon_factory, user_factory


class LogMixin:
    def log(self, comments, action, created=None):
        version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
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
        self.entry = self.log('Oh nøes!', amo.LOG.REJECT_VERSION, self.now)

    def serialize(self, context=None):
        if context is None:
            context = {}
        context['request'] = self.request
        serializer = ActivityLogSerializer(self.entry, context=context)
        return serializer.to_representation(self.entry)

    def test_basic(self):
        result = self.serialize()

        assert result['id'] == self.entry.pk
        assert result['date'] == self.now.isoformat() + 'Z'
        assert result['action'] == 'rejected'
        assert result['action_label'] == 'Rejected'
        assert result['comments'] == 'Oh nøes!'
        assert result['user'] == {
            'name': self.user.name,
        }

    def test_basic_v3(self):
        self.request.version = 'v3'
        result = self.serialize()

        assert result['id'] == self.entry.pk
        assert result['date'] == self.now.isoformat() + 'Z'
        assert result['action'] == 'rejected'
        assert result['action_label'] == 'Rejected'
        assert result['comments'] == 'Oh nøes!'
        # For backwards-compatibility in API v3 the id, url and username are
        # present but empty.
        assert result['user'] == {
            'id': None,
            'url': None,
            'username': None,
            'name': self.user.name,
        }

    def test_should_highlight(self):
        result = self.serialize(context={'to_highlight': [self.entry.pk]})

        assert result['id'] == self.entry.pk
        assert result['highlight']

    def test_should_not_highlight(self):
        no_highlight = self.log('something élse', amo.LOG.REJECT_VERSION)

        result = self.serialize(context={'to_highlight': [no_highlight.pk]})

        assert result['id'] == self.entry.pk
        assert not result['highlight']

    def test_sanitized_activity_detail_not_exposed_to_developer(self):
        self.entry = self.log('ßäď ŞŤųƒƒ', amo.LOG.REQUEST_ADMIN_REVIEW_THEME)
        result = self.serialize()

        assert result['action_label'] == (amo.LOG.REQUEST_ADMIN_REVIEW_THEME.short)
        # Comments should be the santized text rather than the actual content.
        assert result['comments'] == amo.LOG.REQUEST_ADMIN_REVIEW_THEME.sanitize
        assert result['comments'].startswith(
            'The add-on has been flagged for Admin Review.'
        )

    def test_log_entry_without_details(self):
        # Create a log but without a details property.
        self.entry = ActivityLog.create(
            amo.LOG.APPROVAL_NOTES_CHANGED,
            self.addon,
            self.addon.find_latest_version(channel=amo.CHANNEL_LISTED),
            user=self.user,
        )
        result = self.serialize()
        # Should output an empty string.
        assert result['comments'] == ''
