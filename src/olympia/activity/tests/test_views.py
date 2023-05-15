import json
import io
from unittest import mock

from datetime import datetime, timedelta

from django.conf import settings
from django.test.utils import override_settings

from rest_framework.exceptions import ErrorDetail
from rest_framework.test import APIRequestFactory

from olympia import amo
from olympia.activity.models import ActivityLog, ActivityLogToken, GENERIC_USER_NAME
from olympia.activity.tests.test_serializers import LogMixin
from olympia.activity.tests.test_utils import sample_message_content
from olympia.activity.views import inbound_email, InboundEmailIPPermission
from olympia.addons.models import (
    AddonUser,
    AddonRegionalRestrictions,
    AddonReviewerFlags,
)
from olympia.addons.utils import generate_addon_guid
from olympia.amo.tests import (
    APITestClientSessionID,
    TestCase,
    addon_factory,
    reverse_ns,
    user_factory,
    version_factory,
)
from olympia.constants.reviewers import REVIEWER_STANDARD_REPLY_TIME
from olympia.users.models import UserProfile
from olympia.versions.utils import get_review_due_date


class ReviewNotesViewSetDetailMixin(LogMixin):
    """Tests that play with addon state and permissions. Shared between review
    note viewset detail tests since both need to react the same way."""

    def _test_url(self):
        raise NotImplementedError

    def _set_tested_url(self, pk=None, version_pk=None, addon_pk=None):
        raise NotImplementedError

    def _login_developer(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)

    def _login_reviewer(self, permission='Addons:Review'):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, permission)
        self.client.login_api(user)

    def _login_unlisted_reviewer(self, permission='Addons:ReviewUnlisted'):
        user = UserProfile.objects.create(username='reviewer-unlisted')
        self.grant_permission(user, permission)
        self.client.login_api(user)

    def test_get_by_id(self):
        self._login_developer()
        self._test_url()

    def test_get_by_id_reviewer(self):
        self._login_reviewer()
        self._test_url()

    def test_get_anonymous(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_get_no_rights(self):
        self.client.login_api(UserProfile.objects.create(username='joe'))
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_not_public_reviewer(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        self._login_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_public_developer(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        self._login_developer()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_simple_reviewer(self):
        self.make_addon_unlisted(self.addon)
        self._login_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_not_listed_specific_reviewer(self):
        self.make_addon_unlisted(self.addon)
        self._login_reviewer(permission='Addons:ReviewUnlisted')
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_unlisted_viewer(self):
        self.make_addon_unlisted(self.addon)
        self._login_reviewer(permission='ReviewerTools:ViewUnlisted')
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_author(self):
        self.make_addon_unlisted(self.addon)
        self._login_developer()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted(self):
        self.addon.delete()
        self._login_developer()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get_deleted_reviewer(self):
        self.addon.delete()
        self._login_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get_deleted_admin(self):
        self.addon.delete()
        self._login_reviewer(permission='*:*')
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_disabled_version_reviewer(self):
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._login_reviewer()
        self._test_url()

    def test_disabled_version_developer(self):
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._login_developer()
        self._test_url()

    def test_deleted_version_regular_reviewer(self):
        self.version.delete()

        # There was a listed version, it has been deleted but still, it was
        # there, so listed reviewers should still be able to access.
        self._login_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_deleted_version_developer(self):
        self.version.delete()
        self._login_developer()
        self._test_url()

    def test_get_version_not_found(self):
        self._login_reviewer(permission='*:*')
        self._set_tested_url(version_pk=self.version.pk + 27)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_developer_geo_restricted(self):
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['AB', 'CD']
        )
        self._login_developer()
        response = self.client.get(self.url, HTTP_X_COUNTRY_CODE='fr')
        assert response.status_code == 200

        AddonRegionalRestrictions.objects.filter(addon=self.addon).update(
            excluded_regions=['AB', 'CD', 'FR']
        )
        response = self.client.get(self.url, HTTP_X_COUNTRY_CODE='fr')
        assert response.status_code == 200

    def test_reviewer_geo_restricted(self):
        AddonRegionalRestrictions.objects.create(
            addon=self.addon, excluded_regions=['AB', 'CD']
        )
        self._login_reviewer()
        response = self.client.get(self.url, HTTP_X_COUNTRY_CODE='fr')
        assert response.status_code == 200

        AddonRegionalRestrictions.objects.filter(addon=self.addon).update(
            excluded_regions=['AB', 'CD', 'FR']
        )
        response = self.client.get(self.url, HTTP_X_COUNTRY_CODE='fr')
        assert response.status_code == 200

    def test_user_anonymized_for_developer(self):
        self._login_developer()
        response = self.client.get(self.url)
        result = json.loads(response.content)
        if 'results' in result:
            result = result['results'][0]
        assert result['user']['name'] == GENERIC_USER_NAME

    def test_user_not_anonymized_for_reviewer(self):
        self._login_reviewer()
        response = self.client.get(self.url)
        result = json.loads(response.content)
        if 'results' in result:
            result = result['results'][0]
        assert result['user']['name'] == self.user.name

    def test_user_not_anonymized_for_view_only_reviewer(self):
        user = UserProfile.objects.create(username='view-only-reviewer')
        self.grant_permission(user, 'ReviewerTools:View')
        self.client.login_api(user)
        response = self.client.get(self.url)
        result = json.loads(response.content)
        if 'results' in result:
            result = result['results'][0]
        assert result['user']['name'] == self.user.name

    def test_allowed_action_not_anonymized_for_developer(self):
        self.note = self.log(
            'a reply', amo.LOG.DEVELOPER_REPLY_VERSION, self.days_ago(0)
        )
        self._set_tested_url()
        self._login_developer()
        response = self.client.get(self.url)
        result = json.loads(response.content)
        if 'results' in result:
            result = result['results'][0]
        assert result['user']['name'] == self.user.name


class TestReviewNotesViewSetDetail(ReviewNotesViewSetDetailMixin, TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.user = user_factory()
        self.version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        self.note = self.log('noôo!', amo.LOG.REVIEWER_REPLY_VERSION, self.days_ago(0))
        self._set_tested_url()

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.note.pk
        assert result['action_label'] == amo.LOG.REVIEWER_REPLY_VERSION.short
        assert result['comments'] == 'noôo!'
        assert result['highlight']  # Its the first reply so highlight

    def _set_tested_url(self, pk=None, version_pk=None, addon_pk=None):
        self.url = reverse_ns(
            'version-reviewnotes-detail',
            kwargs={
                'addon_pk': addon_pk or self.addon.pk,
                'version_pk': version_pk or self.version.pk,
                'pk': pk or self.note.pk,
            },
        )

    def test_get_note_not_found(self):
        self._login_reviewer(permission='*:*')
        self._set_tested_url(self.note.pk + 42)
        response = self.client.get(self.url)
        assert response.status_code == 404


class TestReviewNotesViewSetList(ReviewNotesViewSetDetailMixin, TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.user = user_factory()
        self.note = self.log('noôo!', amo.LOG.APPROVE_VERSION, self.days_ago(3))
        self.note2 = self.log(
            'réply!', amo.LOG.DEVELOPER_REPLY_VERSION, self.days_ago(2)
        )
        self.note3 = self.log('yéss!', amo.LOG.REVIEWER_REPLY_VERSION, self.days_ago(1))

        self.version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        self._set_tested_url()

    def test_queries(self):
        self.note4 = self.log(
            'fiiiine', amo.LOG.REVIEWER_REPLY_VERSION, self.days_ago(0)
        )
        self._login_developer()
        with self.assertNumQueries(17):
            # - 2 savepoints because of tests
            # - 2 user and groups
            # - 2 addon and its translations
            # - 1 addon author lookup (permission check)
            # - 1 version (no transforms at all)
            # - 1 count of activity logs
            # - 1 activity logs themselves
            # - 1 user
            # - 2 addon and its translations (repeated because we aren't smart
            #   enough yet to pass that to the activity log queryset, it's
            #   difficult since it's not a FK)
            # - 2 version and its translations (same issue)
            # - 2 for highlighting (repeats the query to fetch the activity log
            #   per version)
            response = self.client.get(self.url)
            assert response.status_code == 200

    def _test_url(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['results']
        assert len(result['results']) == 3

        result_version = result['results'][0]
        assert result_version['id'] == self.note3.pk
        assert result_version['highlight']  # This note is after the dev reply.

        result_version = result['results'][1]
        assert result_version['id'] == self.note2.pk
        assert not result_version['highlight']  # This note is the dev reply.

        result_version = result['results'][2]
        assert result_version['id'] == self.note.pk
        assert not result_version['highlight']  # The dev replied so read it.

    def _set_tested_url(self, pk=None, version_pk=None, addon_pk=None):
        self.url = reverse_ns(
            'version-reviewnotes-list',
            kwargs={
                'addon_pk': addon_pk or self.addon.pk,
                'version_pk': version_pk or self.version.pk,
            },
        )

    def test_admin_activity_hidden_from_developer(self):
        # Add an extra activity note but a type we don't show the developer.
        self.log('sécrets', amo.LOG.COMMENT_VERSION, self.days_ago(0))
        self._login_developer()
        # _test_url will check only the 3 notes defined in setup are there.
        self._test_url()


class TestReviewNotesViewSetCreate(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        super().setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name='My Addôn', slug='my-addon'
        )
        self.version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        self.url = reverse_ns(
            'version-reviewnotes-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': self.version.pk},
        )

    def _post_reply(self):
        return self.client.post(self.url, {'comments': 'comménty McCómm€nt'})

    def get_review_activity_queryset(self):
        return ActivityLog.objects.filter(action__in=amo.LOG_REVIEW_QUEUE_DEVELOPER)

    def test_anonymous_is_401(self):
        assert self._post_reply().status_code == 401
        assert not self.get_review_activity_queryset().exists()

    def test_random_user_is_403(self):
        self.user = user_factory()
        self.client.login_api(self.user)
        response = self._post_reply()
        assert response.status_code == 403
        assert not self.get_review_activity_queryset().exists()

    def test_comments_required(self):
        self.user = user_factory()
        self.user.addonuser_set.create(addon=self.addon)
        self.client.login_api(self.user)
        response = self.client.post(self.url, {})
        assert response.status_code == 400
        assert response.data == {
            'comments': [ErrorDetail(string='This field is required.', code='required')]
        }

    def test_comments_too_long(self):
        self.user = user_factory()
        self.user.addonuser_set.create(addon=self.addon)
        self.client.login_api(self.user)
        response = self.client.post(self.url, {'comments': 'â' * 100001})
        assert response.status_code == 400
        assert response.data == {
            'comments': [
                ErrorDetail(
                    string='Ensure this field has no more than 100000 characters.',
                    code='max_length',
                )
            ]
        }

    def _test_developer_reply(self):
        user_factory(id=settings.TASK_USER_ID)
        self.user = user_factory()
        self.user.addonuser_set.create(addon=self.addon)
        self.client.login_api(self.user)
        assert not self.get_review_activity_queryset().exists()

        response = self._post_reply()
        assert response.status_code == 201
        logs = self.get_review_activity_queryset()
        assert logs.count() == 1

        reply = logs[0]
        rdata = response.data
        assert reply.pk == rdata['id']
        assert (
            str(reply.details['comments']) == rdata['comments'] == 'comménty McCómm€nt'
        )
        assert reply.user == self.user
        assert reply.user.name == rdata['user']['name'] == self.user.name
        assert reply.action == amo.LOG.DEVELOPER_REPLY_VERSION.id
        assert not rdata['highlight']  # developer replies aren't highlighted.

        # Version was set as needing human review for a developer reply.
        self.version.reload()
        assert self.version.needs_human_review
        assert self.version.needshumanreview_set.count() == 1
        assert (
            self.version.needshumanreview_set.get().reason
            == self.version.needshumanreview_set.model.REASON_DEVELOPER_REPLY
        )

    def test_developer_reply_listed(self):
        self._test_developer_reply()
        self.assertCloseToNow(
            self.version.due_date,
            now=get_review_due_date(default_days=REVIEWER_STANDARD_REPLY_TIME),
        )

    def test_developer_reply_unlisted(self):
        self.make_addon_unlisted(self.addon)
        self._test_developer_reply()
        self.assertCloseToNow(
            self.version.due_date,
            now=get_review_due_date(default_days=REVIEWER_STANDARD_REPLY_TIME),
        )

    def test_developer_reply_due_date_already_set(self):
        AddonReviewerFlags.objects.create(addon=self.addon, auto_approval_disabled=True)
        expected_due_date = datetime.now() + timedelta(days=1)
        self.version.file.update(status=amo.STATUS_AWAITING_REVIEW)
        self.version.update(due_date=expected_due_date)
        self._test_developer_reply()
        self.version.reload()
        assert self.version.due_date == expected_due_date

    def _test_reviewer_reply(self, perm):
        self.user = user_factory()
        self.grant_permission(self.user, perm)
        self.client.login_api(self.user)
        assert not self.get_review_activity_queryset().exists()

        response = self._post_reply()
        assert response.status_code == 201
        logs = self.get_review_activity_queryset()
        assert logs.count() == 1

        reply = logs[0]
        rdata = response.data
        assert reply.pk == rdata['id']
        assert (
            str(reply.details['comments']) == rdata['comments'] == 'comménty McCómm€nt'
        )
        assert reply.user == self.user
        assert reply.user.name == rdata['user']['name'] == self.user.name
        assert reply.action == amo.LOG.REVIEWER_REPLY_VERSION.id
        assert rdata['highlight']  # reviewer replies are highlighted.

        # Version wasn't set as needing human review for a reviewer reply.
        self.version.reload()
        assert not self.version.needs_human_review
        assert not self.version.due_date

    def test_reviewer_reply_listed(self):
        self._test_reviewer_reply('Addons:Review')

    def test_reviewer_reply_unlisted(self):
        self.make_addon_unlisted(self.addon)
        self._test_reviewer_reply('Addons:ReviewUnlisted')

    def test_reply_to_deleted_addon_is_404(self):
        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:Review')
        self.addon.delete()
        self.client.login_api(self.user)
        response = self._post_reply()
        assert response.status_code == 404
        assert not self.get_review_activity_queryset().exists()

    def test_reply_to_deleted_version_is_400(self):
        old_version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        new_version = version_factory(addon=self.addon)
        old_version.delete()
        # Just in case, make sure the add-on is still public.
        self.addon.reload()
        assert new_version == self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        assert self.addon.status

        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)
        response = self._post_reply()
        assert response.status_code == 400
        assert not self.get_review_activity_queryset().exists()

    def test_cant_reply_to_old_version(self):
        old_version = self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        old_version.update(created=self.days_ago(1))
        new_version = version_factory(addon=self.addon)
        assert new_version == self.addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        self.user = user_factory()
        self.grant_permission(self.user, 'Addons:Review')
        self.client.login_api(self.user)

        # First check we can reply to new version
        new_url = reverse_ns(
            'version-reviewnotes-list',
            kwargs={'addon_pk': self.addon.pk, 'version_pk': new_version.pk},
        )
        response = self.client.post(new_url, {'comments': 'comménty McCómm€nt'})
        assert response.status_code == 201
        assert self.get_review_activity_queryset().count() == 1

        # The check we can't reply to the old version
        response = self._post_reply()
        assert response.status_code == 400
        assert self.get_review_activity_queryset().count() == 1

    def test_developer_can_reply_to_disabled_version(self):
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_developer_reply()

    def test_reviewer_can_reply_to_disabled_version_listed(self):
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_reviewer_reply('Addons:Review')

    def test_reviewer_can_reply_to_disabled_version_unlisted(self):
        self.make_addon_unlisted(self.addon)
        self.version.file.update(status=amo.STATUS_DISABLED)
        self._test_reviewer_reply('Addons:ReviewUnlisted')


@override_settings(ALLOWED_CLIENTS_EMAIL_API=['10.10.10.10'])
@override_settings(INBOUND_EMAIL_SECRET_KEY='SOME SECRET KEY')
@override_settings(INBOUND_EMAIL_VALIDATION_KEY='validation key')
class TestEmailApi(TestCase):
    def get_request(self, data):
        # Request body should be a bytes string, so it needs to be encoded
        # after having built the json representation of it, then fed into
        # BytesIO().
        datastr = json.dumps(data).encode('utf-8')
        req = APIRequestFactory().post(reverse_ns('inbound-email-api'))
        req.META['REMOTE_ADDR'] = '10.10.10.10'
        req.META['CONTENT_LENGTH'] = len(datastr)
        req.META['CONTENT_TYPE'] = 'application/json'
        req._stream = io.BytesIO(datastr)
        return req

    def get_validation_request(self, data):
        req = APIRequestFactory().post(reverse_ns('inbound-email-api'), data=data)
        req.META['REMOTE_ADDR'] = '10.10.10.10'
        return req

    def test_basic(self):
        user = user_factory()
        self.grant_permission(user, '*:*')
        addon = addon_factory()
        version = addon.find_latest_version(channel=amo.CHANNEL_LISTED)
        req = self.get_request(sample_message_content)

        ActivityLogToken.objects.create(
            user=user, version=version, uuid='5a0b8a83d501412589cc5d562334b46b'
        )

        res = inbound_email(req)
        assert res.status_code == 201
        res.render()
        assert res.content == b'"validation key"'
        logs = ActivityLog.objects.for_addons(addon)
        assert logs.count() == 1
        assert logs.get(action=amo.LOG.REVIEWER_REPLY_VERSION.id)

    def test_ip_allowed(self):
        assert InboundEmailIPPermission().has_permission(self.get_request({}), None)

    def test_ip_denied(self):
        req = self.get_request({})
        req.META['REMOTE_ADDR'] = '10.10.10.1'
        assert not InboundEmailIPPermission().has_permission(req, None)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=42)
    @mock.patch('olympia.activity.tasks.process_email.apply_async')
    def test_content_too_long(self, _mock):
        data = {'Message': 'something', 'SpamScore': 4.56}
        assert len(json.dumps(data)) == 43
        req = self.get_request(data)
        res = inbound_email(req)
        assert not _mock.called
        assert res.status_code == 413
        res.render()
        assert b'Request content length exceeds 42.' in res.content

    @mock.patch('olympia.activity.tasks.process_email.apply_async')
    def test_no_secret_key(self, _mock):
        req = self.get_request({'Message': 'something', 'SpamScore': 4.56})
        res = inbound_email(req)
        assert not _mock.called
        assert res.status_code == 403

    @mock.patch('olympia.activity.tasks.process_email.apply_async')
    def test_wrong_secret_key(self, _mock):
        req = self.get_request(
            {'SecretKey': 'WRONG SECRET', 'Message': 'something', 'SpamScore': 4.56}
        )
        res = inbound_email(req)
        assert not _mock.called
        assert res.status_code == 403

    @mock.patch('olympia.activity.tasks.process_email.apply_async')
    def test_successful(self, _mock):
        req = self.get_request(
            {'SecretKey': 'SOME SECRET KEY', 'Message': 'something', 'SpamScore': 4.56}
        )
        res = inbound_email(req)
        _mock.assert_called_with(('something', 4.56))
        assert res.status_code == 201
        res.render()
        assert res.content == b'"validation key"'

    def test_bad_request(self):
        """Test with no email body."""
        res = inbound_email(self.get_request({'SecretKey': 'SOME SECRET KEY'}))
        assert res.status_code == 400

    @mock.patch('olympia.activity.tasks.process_email.apply_async')
    def test_validation_response(self, _mock):
        req = self.get_validation_request(
            {'SecretKey': 'SOME SECRET KEY', 'Type': 'Validation'}
        )
        res = inbound_email(req)
        assert not _mock.called
        assert res.status_code == 200
        res.render()
        assert res.content == b'"validation key"'

    @mock.patch('olympia.activity.tasks.process_email.apply_async')
    def test_validation_response_wrong_secret(self, _mock):
        req = self.get_validation_request(
            {'SecretKey': 'WRONG SECRET', 'Type': 'Validation'}
        )
        res = inbound_email(req)
        assert not _mock.called
        assert res.status_code == 403
