from datetime import datetime
from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser
from django.test.client import RequestFactory

from rest_framework.serializers import ValidationError

from olympia import amo
from olympia.abuse.models import AbuseReport
from olympia.abuse.serializers import (
    AddonAbuseReportSerializer,
    CollectionAbuseReportSerializer,
    RatingAbuseReportSerializer,
    UserAbuseReportSerializer,
)
from olympia.accounts.serializers import BaseUserSerializer
from olympia.amo.tests import TestCase, addon_factory, collection_factory, user_factory
from olympia.constants.abuse import ILLEGAL_CATEGORIES, ILLEGAL_SUBCATEGORIES
from olympia.ratings.models import Rating


class TestAddonAbuseReportSerializer(TestCase):
    def serialize(self, report, context=None):
        return dict(AddonAbuseReportSerializer(report, context=context or {}).data)

    def test_output_with_view_and_addon_object(self):
        addon = addon_factory(guid='@guid')
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        view.get_guid.return_value = addon.guid
        view.get_target_object.return_value.slug = addon.slug
        view.get_target_object.return_value.pk = addon.pk
        context = {
            'request': request,
            'view': view,
        }
        report = AbuseReport(guid=addon.guid, message='bad stuff')
        serialized = self.serialize(report, context=context)
        assert serialized == {
            'reporter': None,
            'reporter_email': None,
            'reporter_name': None,
            'addon': {'guid': addon.guid, 'id': addon.pk, 'slug': addon.slug},
            'message': 'bad stuff',
            'addon_install_method': None,
            'addon_install_origin': None,
            'addon_install_source': None,
            'addon_install_source_url': None,
            'addon_name': None,
            'addon_signature': None,
            'addon_summary': None,
            'addon_version': None,
            'app': 'firefox',
            'lang': None,
            'appversion': None,
            'client_id': None,
            'install_date': None,
            'operating_system': None,
            'operating_system_version': None,
            'reason': None,
            'report_entry_point': None,
            'location': None,
            'illegal_category': None,
            'illegal_subcategory': None,
        }

    def test_guid_report_addon_exists_doesnt_matter(self):
        addon = addon_factory(guid='@guid')
        report = AbuseReport(guid=addon.guid, message='bad stuff')
        serialized = self.serialize(report)
        assert serialized == {
            'reporter': None,
            'reporter_email': None,
            'reporter_name': None,
            'addon': {'guid': addon.guid, 'id': None, 'slug': None},
            'message': 'bad stuff',
            'addon_install_method': None,
            'addon_install_origin': None,
            'addon_install_source': None,
            'addon_install_source_url': None,
            'addon_name': None,
            'addon_signature': None,
            'addon_summary': None,
            'addon_version': None,
            'app': 'firefox',
            'lang': None,
            'appversion': None,
            'client_id': None,
            'install_date': None,
            'operating_system': None,
            'operating_system_version': None,
            'reason': None,
            'report_entry_point': None,
            'location': None,
            'illegal_category': None,
            'illegal_subcategory': None,
        }

    def test_guid_report(self):
        report = AbuseReport(guid='@guid', message='bad stuff')
        serialized = self.serialize(report)
        assert serialized == {
            'reporter': None,
            'reporter_email': None,
            'reporter_name': None,
            'addon': {'guid': '@guid', 'id': None, 'slug': None},
            'message': 'bad stuff',
            'addon_install_method': None,
            'addon_install_origin': None,
            'addon_install_source': None,
            'addon_install_source_url': None,
            'addon_name': None,
            'addon_signature': None,
            'addon_summary': None,
            'addon_version': None,
            'app': 'firefox',
            'lang': None,
            'appversion': None,
            'client_id': None,
            'install_date': None,
            'operating_system': None,
            'operating_system_version': None,
            'reason': None,
            'report_entry_point': None,
            'location': None,
            'illegal_category': None,
            'illegal_subcategory': None,
        }

    def test_guid_report_to_internal_value_with_some_fancy_parameters(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        view.get_guid.return_value = '@someguid'
        view.get_target_object.return_value = None
        context = {
            'request': request,
            'view': view,
        }
        data = {
            'addon': '@someguid',
            'message': 'I am the messagê',
            'addon_install_method': 'url',
            'addon_install_origin': 'http://somewhere.com/',
            'addon_install_source': 'amo',
            'addon_install_source_url': 'https://example.com/sourceme',
            'addon_name': 'Fancy add-on nâme',
            'addon_signature': None,
            'addon_summary': 'A summary',
            'addon_version': '42.42.0',
            'app': 'firefox',
            'lang': 'en-US',
            'appversion': '64.0',
            'client_id': (
                'ed3480638a9c48f3bc16c2becde0de74d44d80f1f8cf463b937745572c109ed0'
            ),
            'install_date': '2019-02-25 12:19',
            'operating_system': 'Ôperating System!',
            'operating_system_version': '2019',
            'reason': 'broken',
            'report_entry_point': 'uninstall',
        }
        result = dict(
            AddonAbuseReportSerializer(data, context=context).to_internal_value(data)
        )
        expected = {
            'addon_install_method': AbuseReport.ADDON_INSTALL_METHODS.URL,
            'addon_install_origin': 'http://somewhere.com/',
            'addon_install_source': AbuseReport.ADDON_INSTALL_SOURCES.AMO,
            'addon_install_source_url': 'https://example.com/sourceme',
            'addon_name': 'Fancy add-on nâme',
            'addon_signature': None,
            'addon_summary': 'A summary',
            'addon_version': '42.42.0',
            'application': amo.FIREFOX.id,
            'application_locale': 'en-US',
            'application_version': '64.0',
            'client_id': (
                'ed3480638a9c48f3bc16c2becde0de74d44d80f1f8cf463b937745572c109ed0'
            ),
            'country_code': '',
            'guid': '@someguid',
            'install_date': datetime(2019, 2, 25, 12, 19),
            'message': 'I am the messagê',
            'operating_system': 'Ôperating System!',
            'operating_system_version': '2019',
            'reason': AbuseReport.REASONS.BROKEN,
            'report_entry_point': AbuseReport.REPORT_ENTRY_POINTS.UNINSTALL,
        }
        assert result == expected

    def test_with_invalid_client_id(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        view.get_guid.return_value = '@someguid'
        view.get_target_object.return_value = None
        context = {
            'request': request,
            'view': view,
        }
        data = {
            'addon': '@someguid',
            'message': 'I am the messagê',
            'addon_install_method': 'url',
            'addon_install_origin': 'http://somewhere.com/',
            'addon_install_source': 'amo',
            'addon_install_source_url': 'https://example.com/sourceme',
            'addon_name': 'Fancy add-on nâme',
            'addon_signature': None,
            'addon_summary': 'A summary',
            'addon_version': '42.42.0',
            'app': 'firefox',
            'lang': 'en-US',
            'appversion': '64.0',
            'client_id': 'someinvalidclientid',
            'install_date': '2019-02-25 12:19',
            'operating_system': 'Ôperating System!',
            'operating_system_version': '2019',
            'reason': 'broken',
            'report_entry_point': 'uninstall',
        }
        with self.assertRaises(ValidationError) as e:
            AddonAbuseReportSerializer(data, context=context).to_internal_value(data)
        assert str(e.exception.detail['client_id'][0]) == 'Invalid value'

    def test_explicitly_null_client_id(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        view.get_guid.return_value = '@someguid'
        view.get_target_object.return_value = None
        context = {
            'request': request,
            'view': view,
        }
        data = {'addon': '@someguid', 'message': 'I am the messagê', 'client_id': None}
        result = dict(
            AddonAbuseReportSerializer(data, context=context).to_internal_value(data)
        )
        assert result['guid']
        assert result['message']
        assert result['client_id'] is None

    def test_non_string_client_id(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        view.get_guid.return_value = '@someguid'
        view.get_target_object.return_value = None
        context = {
            'request': request,
            'view': view,
        }
        data = {'addon': '@someguid', 'message': 'I am the messagê', 'client_id': 42}
        with self.assertRaises(ValidationError) as e:
            AddonAbuseReportSerializer(data, context=context).to_internal_value(data)
        assert str(e.exception.detail['client_id'][0]) == 'Invalid value'


class TestUserAbuseReportSerializer(TestCase):
    def serialize(self, report, context=None):
        return dict(UserAbuseReportSerializer(report, context=context or {}).data)

    def test_user_report(self):
        user = user_factory()
        report = AbuseReport(user=user, message='bad stuff')
        serialized = self.serialize(report)
        serialized_user = BaseUserSerializer(user).data
        assert serialized == {
            'reporter': None,
            'reporter_email': None,
            'reporter_name': None,
            'user': serialized_user,
            'message': 'bad stuff',
            'lang': None,
            'reason': None,
            'illegal_category': None,
            'illegal_subcategory': None,
        }


class TestRatingAbuseReportSerializer(TestCase):
    def serialize(self, report, context=None):
        return dict(RatingAbuseReportSerializer(report, context=context or {}).data)

    def test_rating_report(self):
        user = user_factory()
        addon = addon_factory()
        rating = Rating.objects.create(
            body='evil rating', addon=addon, user=user, rating=1
        )
        report = AbuseReport(
            rating=rating,
            message='bad stuff',
            reason=AbuseReport.REASONS.ILLEGAL,
            illegal_category=ILLEGAL_CATEGORIES.ANIMAL_WELFARE,
            illegal_subcategory=ILLEGAL_SUBCATEGORIES.OTHER,
        )
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        view.get_target_object.return_value = rating
        context = {
            'request': request,
            'view': view,
        }
        serialized = self.serialize(report, context=context)
        assert serialized == {
            'reporter': None,
            'reporter_email': None,
            'reporter_name': None,
            'rating': {
                'id': rating.pk,
            },
            'reason': 'illegal',
            'message': 'bad stuff',
            'lang': None,
            'illegal_category': 'animal_welfare',
            'illegal_subcategory': 'other',
        }


class TestCollectionAbuseReportSerializer(TestCase):
    def serialize(self, report, context=None):
        return dict(CollectionAbuseReportSerializer(report, context=context or {}).data)

    def test_collection_report(self):
        collection = collection_factory()
        report = AbuseReport(
            collection=collection,
            message='this is some spammy stûff',
            reason=AbuseReport.REASONS.FEEDBACK_SPAM,
        )
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        view = Mock()
        view.get_target_object.return_value = collection
        context = {
            'request': request,
            'view': view,
        }
        serialized = self.serialize(report, context=context)
        assert serialized == {
            'reporter': None,
            'reporter_email': None,
            'reporter_name': None,
            'collection': {
                'id': collection.pk,
            },
            'reason': 'feedback_spam',
            'message': 'this is some spammy stûff',
            'lang': None,
            'illegal_category': None,
            'illegal_subcategory': None,
        }
