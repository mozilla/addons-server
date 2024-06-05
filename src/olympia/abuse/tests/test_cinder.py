import json
import os.path
import random
from unittest import mock

from django.conf import settings

import responses
import waffle
from waffle.testutils import override_switch

from olympia import amo, core
from olympia.abuse.models import AbuseReport, CinderJob
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon, Preview
from olympia.amo.tests import (
    TestCase,
    addon_factory,
    collection_factory,
    user_factory,
    version_factory,
)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.bandwagon.models import Collection, CollectionAddon
from olympia.constants.abuse import DECISION_ACTIONS
from olympia.constants.promoted import NOT_PROMOTED, NOTABLE, RECOMMENDED
from olympia.ratings.models import Rating
from olympia.reviewers.models import NeedsHumanReview
from olympia.users.models import UserProfile
from olympia.versions.models import VersionPreview

from ..cinder import (
    CinderAddon,
    CinderAddonHandledByReviewers,
    CinderCollection,
    CinderRating,
    CinderReport,
    CinderUnauthenticatedReporter,
    CinderUser,
)


class BaseTestCinderCase:
    cinder_class = None  # Override in child classes
    expected_queue_suffix = None  # Override in child classes
    expected_queries_for_report = -1  # Override in child classes

    def test_queue(self):
        target = self._create_dummy_target()
        cinder_entity = self.cinder_class(target)
        assert cinder_entity.queue_suffix == self.expected_queue_suffix
        assert (
            cinder_entity.queue
            == f'{settings.CINDER_QUEUE_PREFIX}{cinder_entity.queue_suffix}'
        )

    def _create_dummy_target(self, **kwargs):
        raise NotImplementedError

    def _guess_abuse_report_kwargs(self, target):
        if isinstance(target, Addon):
            return {'guid': target.guid}
        elif isinstance(target, UserProfile):
            return {'user': target}
        elif isinstance(target, Rating):
            return {'rating': target}
        elif isinstance(target, Collection):
            return {'collection': target}

    def _test_report(self, target):
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=400,
        )
        abuse_report = AbuseReport.objects.create(
            **self._guess_abuse_report_kwargs(target)
        )
        # Force a reload on the abuse report and use abuse_report.target to
        # clear any caching on the target, to force assertNumQueries to count
        # queries for related objects on the target we might already have
        # loaded before.
        abuse_report.reload()
        report = CinderReport(abuse_report)
        cinder_instance = self.cinder_class(abuse_report.target)
        with self.assertNumQueries(self.expected_queries_for_report):
            assert cinder_instance.report(report=report, reporter=None) == '1234-xyz'
        assert (
            cinder_instance.report(report=report, reporter=CinderUser(user_factory()))
            == '1234-xyz'
        )
        assert (
            cinder_instance.report(
                report=report,
                reporter=CinderUnauthenticatedReporter(name='name', email='e@ma.il'),
            )
            == '1234-xyz'
        )
        # Last response is a 400, we raise for that.
        with self.assertRaises(ConnectionError):
            cinder_instance.report(report=report, reporter=None)

    def test_build_report_payload(self):
        raise NotImplementedError

    def test_report(self):
        self._test_report(self._create_dummy_target())

    def _test_appeal(self, appealer, cinder_instance=None):
        fake_decision_id = 'decision-id-to-appeal-666'
        cinder_instance = cinder_instance or self.cinder_class(
            self._create_dummy_target()
        )

        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '67890-abc'},
            status=201,
        )
        assert (
            cinder_instance.appeal(
                decision_cinder_id=fake_decision_id,
                appeal_text='reason',
                appealer=appealer,
            )
            == '67890-abc'
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}appeal',
            json={'external_id': '67890-abc'},
            status=400,
        )
        with self.assertRaises(ConnectionError):
            cinder_instance.appeal(
                decision_cinder_id=fake_decision_id,
                appeal_text='reason',
                appealer=appealer,
            )

    def test_appeal_anonymous(self):
        self._test_appeal(CinderUser(user_factory()))

    def test_appeal_logged_in(self):
        self._test_appeal(CinderUnauthenticatedReporter('itsme', 'm@r.io'))

    def test_get_str(self):
        instance = self.cinder_class(self._create_dummy_target())
        assert instance.get_str(123) == '123'
        assert instance.get_str(None) == ''
        assert instance.get_str(' ') == ''


class TestCinderAddon(BaseTestCinderCase, TestCase):
    cinder_class = CinderAddon
    # 2 queries expected:
    # - Authors (can't use the listed_authors transformer, we want non-listed as well,
    #            and we have custom limits for batch-sending relationships)
    # - Promoted add-on
    expected_queries_for_report = 2
    expected_queue_suffix = 'listings'

    def _create_dummy_target(self, **kwargs):
        return addon_factory(**kwargs)

    def test_queue_theme(self):
        target = self._create_dummy_target(type=amo.ADDON_STATICTHEME)
        cinder_entity = self.cinder_class(target)
        expected_queue_suffix = 'themes'
        assert cinder_entity.queue_suffix == expected_queue_suffix
        assert (
            cinder_entity.queue
            == f'{settings.CINDER_QUEUE_PREFIX}{cinder_entity.queue_suffix}'
        )

    def test_build_report_payload(self):
        addon = self._create_dummy_target(
            homepage='https://home.example.com',
            support_email='support@example.com',
            support_url='https://support.example.com/',
            description='Sôme description',
            privacy_policy='Söme privacy policy',
            version_kw={'release_notes': 'Søme release notes'},
        )
        message = ' bad addon!'
        cinder_addon = self.cinder_class(addon)
        encoded_message = cinder_addon.get_str(message)
        abuse_report = AbuseReport.objects.create(guid=addon.guid, message=message)
        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data == {
            'queue_slug': cinder_addon.queue,
            'entity_type': 'amo_addon',
            'entity': {
                'id': str(addon.pk),
                'average_daily_users': addon.average_daily_users,
                'created': str(addon.created),
                'description': str(addon.description),
                'guid': addon.guid,
                'homepage': str(addon.homepage),
                'last_updated': str(addon.last_updated),
                'name': str(addon.name),
                'privacy_policy': 'Söme privacy policy',
                'promoted': '',
                'release_notes': 'Søme release notes',
                'slug': addon.slug,
                'summary': str(addon.summary),
                'support_email': str(addon.support_email),
                'support_url': str(addon.support_url),
                'version': addon.current_version.version,
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    }
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(addon.pk),
                        'target_type': 'amo_addon',
                    }
                ],
            },
        }

        # if we have an email or name
        name = 'Foxy McFox'
        email = 'foxy@mozilla'
        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report),
            reporter=CinderUnauthenticatedReporter(name, email),
        )
        assert data['context'] == {
            'entities': [
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': encoded_message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
                {
                    'entity_type': 'amo_unauthenticated_reporter',
                    'attributes': {
                        'id': f'{name} : {email}',
                        'name': name,
                        'email': email,
                    },
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'source_id': f'{name} : {email}',
                    'source_type': 'amo_unauthenticated_reporter',
                    'target_id': str(abuse_report.pk),
                    'target_type': 'amo_report',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }

        # and if the reporter is authenticated
        reporter_user = user_factory()
        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report), reporter=CinderUser(reporter_user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': encoded_message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(reporter_user.pk),
                        'created': str(reporter_user.created),
                        'name': reporter_user.display_name,
                        'email': reporter_user.email,
                        'fxa_id': reporter_user.fxa_id,
                    },
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'source_id': str(reporter_user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(abuse_report.pk),
                    'target_type': 'amo_report',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }

    def test_build_report_payload_promoted_recommended(self):
        addon = self._create_dummy_target(
            homepage='https://home.example.com',
            support_email='support@example.com',
            support_url='https://support.example.com/',
            description='Sôme description',
            privacy_policy='Söme privacy policy',
            version_kw={'release_notes': 'Søme release notes'},
        )
        self.make_addon_promoted(addon, group=RECOMMENDED)
        message = ' bad addon!'
        cinder_addon = self.cinder_class(addon)
        encoded_message = cinder_addon.get_str(message)
        abuse_report = AbuseReport.objects.create(guid=addon.guid, message=message)
        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data == {
            'queue_slug': cinder_addon.queue,
            'entity_type': 'amo_addon',
            'entity': {
                'id': str(addon.pk),
                'average_daily_users': addon.average_daily_users,
                'created': str(addon.created),
                'description': str(addon.description),
                'guid': addon.guid,
                'homepage': str(addon.homepage),
                'last_updated': str(addon.last_updated),
                'name': str(addon.name),
                'privacy_policy': 'Söme privacy policy',
                'promoted': 'Recommended',
                'release_notes': 'Søme release notes',
                'slug': addon.slug,
                'summary': str(addon.summary),
                'support_email': str(addon.support_email),
                'support_url': str(addon.support_url),
                'version': addon.current_version.version,
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    }
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(addon.pk),
                        'target_type': 'amo_addon',
                    }
                ],
            },
        }

    def test_build_report_payload_promoted_notable(self):
        addon = self._create_dummy_target(
            homepage='https://home.example.com',
            support_email='support@example.com',
            support_url='https://support.example.com/',
            description='Sôme description',
            privacy_policy='Söme privacy policy',
            version_kw={'release_notes': 'Søme release notes'},
        )
        self.make_addon_promoted(addon, group=NOTABLE)
        message = ' bad addon!'
        cinder_addon = self.cinder_class(addon)
        encoded_message = cinder_addon.get_str(message)
        abuse_report = AbuseReport.objects.create(guid=addon.guid, message=message)
        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data == {
            'queue_slug': cinder_addon.queue,
            'entity_type': 'amo_addon',
            'entity': {
                'id': str(addon.pk),
                'average_daily_users': addon.average_daily_users,
                'created': str(addon.created),
                'description': str(addon.description),
                'guid': addon.guid,
                'homepage': str(addon.homepage),
                'last_updated': str(addon.last_updated),
                'name': str(addon.name),
                'privacy_policy': 'Söme privacy policy',
                'promoted': 'Notable',
                'release_notes': 'Søme release notes',
                'slug': addon.slug,
                'summary': str(addon.summary),
                'support_email': str(addon.support_email),
                'support_url': str(addon.support_url),
                'version': addon.current_version.version,
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    }
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(addon.pk),
                        'target_type': 'amo_addon',
                    }
                ],
            },
        }

        self.make_addon_promoted(addon, NOT_PROMOTED)
        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data['entity']['promoted'] == ''

    def test_build_report_payload_with_author(self):
        author = user_factory()
        addon = self._create_dummy_target(users=[author])
        message = '@bad addon!'
        cinder_addon = self.cinder_class(addon)
        abuse_report = AbuseReport.objects.create(guid=addon.guid, message=message)

        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(author.id),
                        'created': str(author.created),
                        'name': author.display_name,
                        'email': author.email,
                        'fxa_id': author.fxa_id,
                    },
                },
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
            ],
            'relationships': [
                {
                    'source_id': str(author.id),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                },
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
            ],
        }

        # and if the reporter is authenticated
        reporter_user = user_factory()
        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report), reporter=CinderUser(reporter_user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(author.id),
                        'created': str(author.created),
                        'name': author.display_name,
                        'email': author.email,
                        'fxa_id': author.fxa_id,
                    },
                },
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(reporter_user.pk),
                        'created': str(reporter_user.created),
                        'name': reporter_user.display_name,
                        'email': reporter_user.email,
                        'fxa_id': reporter_user.fxa_id,
                    },
                },
            ],
            'relationships': [
                {
                    'source_id': str(author.id),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                },
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'source_id': str(reporter_user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(abuse_report.pk),
                    'target_type': 'amo_report',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }

    def test_build_report_payload_with_author_and_reporter_being_the_same(self):
        user = user_factory()
        addon = self._create_dummy_target(users=[user])
        cinder_addon = self.cinder_class(addon)
        message = 'self reporting! '
        encoded_message = cinder_addon.get_str(message)
        abuse_report = AbuseReport.objects.create(guid=addon.guid, message=message)

        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report), reporter=CinderUser(user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(user.pk),
                        'created': str(user.created),
                        'name': user.display_name,
                        'email': user.email,
                        'fxa_id': user.fxa_id,
                    },
                },
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': encoded_message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
            ],
            'relationships': [
                {
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                },
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(abuse_report.pk),
                    'target_type': 'amo_report',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }

    @mock.patch('olympia.abuse.cinder.create_signed_url_for_file_backup')
    @mock.patch('olympia.abuse.cinder.copy_file_to_backup_storage')
    @mock.patch('olympia.abuse.cinder.backup_storage_enabled', lambda: True)
    def test_build_report_payload_with_previews_and_icon(
        self,
        copy_file_to_backup_storage_mock,
        create_signed_url_for_file_backup_mock,
    ):
        copy_file_to_backup_storage_mock.side_effect = (
            lambda fpath, type_: os.path.basename(fpath)
        )
        create_signed_url_for_file_backup_mock.side_effect = (
            lambda rpath: f'https://cloud.example.com/{rpath}?some=thing'
        )
        addon = self._create_dummy_target()
        addon.update(icon_type='image/jpeg')
        self.root_storage.copy_stored_file(
            get_image_path('sunbird-small.png'), addon.get_icon_path(128)
        )
        for position in range(1, 3):
            preview = Preview.objects.create(addon=addon, position=position)
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.thumbnail_path
            )
        (p0, p1) = list(addon.previews.all())
        Preview.objects.create(addon=addon, position=5)  # No file, ignored
        cinder_addon = self.cinder_class(addon)
        message = ' report with images '
        encoded_message = cinder_addon.get_str(message)
        abuse_report = AbuseReport.objects.create(guid=addon.guid, message=message)

        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report),
            reporter=None,
        )
        assert data == {
            'queue_slug': cinder_addon.queue,
            'entity_type': 'amo_addon',
            'entity': {
                'id': str(addon.pk),
                'average_daily_users': addon.average_daily_users,
                'description': '',
                'created': str(addon.created),
                'homepage': None,
                'guid': addon.guid,
                'icon': {
                    'mime_type': 'image/png',
                    'value': f'https://cloud.example.com/{addon.pk}-128.png?some=thing',
                },
                'last_updated': str(addon.last_updated),
                'name': str(addon.name),
                'previews': [
                    {
                        'mime_type': 'image/jpeg',
                        'value': f'https://cloud.example.com/{p0.pk}.jpg?some=thing',
                    },
                    {
                        'mime_type': 'image/jpeg',
                        'value': f'https://cloud.example.com/{p1.pk}.jpg?some=thing',
                    },
                ],
                'privacy_policy': '',
                'promoted': '',
                'release_notes': '',
                'slug': addon.slug,
                'summary': str(addon.summary),
                'support_email': None,
                'support_url': None,
                'version': str(addon.current_version.version),
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    },
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(addon.pk),
                        'target_type': 'amo_addon',
                    },
                ],
            },
        }

    @mock.patch('olympia.abuse.cinder.create_signed_url_for_file_backup')
    @mock.patch('olympia.abuse.cinder.copy_file_to_backup_storage')
    @mock.patch('olympia.abuse.cinder.backup_storage_enabled', lambda: True)
    def test_build_report_payload_with_theme_previews(
        self,
        copy_file_to_backup_storage_mock,
        create_signed_url_for_file_backup_mock,
    ):
        copy_file_to_backup_storage_mock.side_effect = (
            lambda fpath, type_: os.path.basename(fpath)
        )
        create_signed_url_for_file_backup_mock.side_effect = (
            lambda rpath: f'https://cloud.example.com/{rpath}?what=ever'
        )
        addon = self._create_dummy_target()
        addon.update(type=amo.ADDON_STATICTHEME)
        for position in range(1, 3):
            preview = VersionPreview.objects.create(
                version=addon.current_version, position=position
            )
            self.root_storage.copy_stored_file(
                get_image_path('preview_landscape.jpg'), preview.thumbnail_path
            )
        p0 = addon.current_version.previews.all().get(
            position=amo.THEME_PREVIEW_RENDERINGS['amo']['position']
        )
        VersionPreview.objects.create(
            version=addon.current_version, position=5
        )  # No file, ignored
        cinder_addon = self.cinder_class(addon)
        message = 'report with images'
        encoded_message = cinder_addon.get_str(message)
        abuse_report = AbuseReport.objects.create(guid=addon.guid, message=message)

        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report),
            reporter=None,
        )
        assert data == {
            'queue_slug': cinder_addon.queue,
            'entity_type': 'amo_addon',
            'entity': {
                'id': str(addon.pk),
                'average_daily_users': addon.average_daily_users,
                'description': '',
                'created': str(addon.created),
                'guid': addon.guid,
                'homepage': None,
                'last_updated': str(addon.last_updated),
                'name': str(addon.name),
                'previews': [
                    {
                        'mime_type': 'image/png',
                        'value': f'https://cloud.example.com/{p0.pk}.png?what=ever',
                    },
                ],
                'privacy_policy': '',
                'promoted': '',
                'release_notes': '',
                'slug': addon.slug,
                'summary': str(addon.summary),
                'support_email': None,
                'support_url': None,
                'version': str(addon.current_version.version),
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    },
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(addon.pk),
                        'target_type': 'amo_addon',
                    },
                ],
            },
        }

    @mock.patch.object(CinderAddon, 'RELATIONSHIPS_BATCH_SIZE', 2)
    def test_build_report_payload_only_includes_first_batch_of_relationships(self):
        addon = self._create_dummy_target()
        for _ in range(0, 6):
            addon.authors.add(user_factory())
        cinder_addon = self.cinder_class(addon)
        message = 'report for lots of relationships'
        abuse_report = AbuseReport.objects.create(guid=addon.guid, message=message)
        data = cinder_addon.build_report_payload(
            report=CinderReport(abuse_report),
            reporter=None,
        )
        # 2 addon<->user (out of 6) + 1 anonymous report
        assert len(data['context']['relationships']) == 3
        assert len(data['context']['entities']) == 3
        first_author = addon.authors.all()[0]
        second_author = addon.authors.all()[1]
        assert data['context'] == {
            'entities': [
                {
                    'attributes': {
                        'created': str(first_author.created),
                        'email': str(first_author.email),
                        'fxa_id': None,
                        'id': str(first_author.pk),
                        'name': '',
                    },
                    'entity_type': 'amo_user',
                },
                {
                    'attributes': {
                        'created': str(second_author.created),
                        'email': str(second_author.email),
                        'fxa_id': None,
                        'id': str(second_author.pk),
                        'name': '',
                    },
                    'entity_type': 'amo_user',
                },
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': 'report for lots of relationships',
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(first_author.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(second_author.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
            ],
        }

    @mock.patch.object(CinderAddon, 'RELATIONSHIPS_BATCH_SIZE', 2)
    def test_report_additional_context(self):
        addon = self._create_dummy_target()
        for _ in range(0, 6):
            addon.authors.add(user_factory())
        cinder_addon = self.cinder_class(addon)

        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}graph/',
            status=202,
        )

        cinder_addon.report_additional_context()
        assert len(responses.calls) == 2
        data = json.loads(responses.calls[0].request.body)
        # The first 2 authors should be skipped, they would have been sent with
        # the main report request.
        third_author = addon.authors.all()[2]
        fourth_author = addon.authors.all()[3]
        assert data == {
            'entities': [
                {
                    'attributes': {
                        'created': str(third_author.created),
                        'email': str(third_author.email),
                        'fxa_id': None,
                        'id': str(third_author.pk),
                        'name': '',
                    },
                    'entity_type': 'amo_user',
                },
                {
                    'attributes': {
                        'created': str(fourth_author.created),
                        'email': str(fourth_author.email),
                        'fxa_id': None,
                        'id': str(fourth_author.pk),
                        'name': '',
                    },
                    'entity_type': 'amo_user',
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(third_author.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(fourth_author.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
            ],
        }
        data = json.loads(responses.calls[1].request.body)
        fifth_author = addon.authors.all()[4]
        sixth_author = addon.authors.all()[5]
        assert data == {
            'entities': [
                {
                    'attributes': {
                        'created': str(fifth_author.created),
                        'email': str(fifth_author.email),
                        'fxa_id': None,
                        'id': str(fifth_author.pk),
                        'name': '',
                    },
                    'entity_type': 'amo_user',
                },
                {
                    'attributes': {
                        'created': str(sixth_author.created),
                        'email': str(sixth_author.email),
                        'fxa_id': None,
                        'id': str(sixth_author.pk),
                        'name': '',
                    },
                    'entity_type': 'amo_user',
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(fifth_author.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(sixth_author.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                },
            ],
        }

    @mock.patch.object(CinderAddon, 'RELATIONSHIPS_BATCH_SIZE', 2)
    def test_report_additional_context_error(self):
        addon = self._create_dummy_target()
        for _ in range(0, 6):
            addon.authors.add(user_factory())
        cinder_addon = self.cinder_class(addon)

        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}graph/',
            status=400,
        )

        with self.assertRaises(ConnectionError):
            cinder_addon.report_additional_context()


@override_switch('dsa-abuse-reports-review', active=True)
@override_switch('dsa-appeals-review', active=True)
class TestCinderAddonHandledByReviewers(TestCinderAddon):
    cinder_class = CinderAddonHandledByReviewers
    # Expected queries is a bit larger here because of activity log and
    # needs human review checks + insertion.
    # - 1 Fetch Version
    # - 2 Fetch Translations for that Version
    # - 3 Fetch NeedsHumanReview
    # - 4 Create NeedsHumanReview
    # - 5 Fetch NeedsHumanReview
    # - 6 Update due date on Versions
    # - 7 Fetch Latest signed Version
    # - 8 Fetch task user
    # - 9 Create ActivityLog
    # - 10 Create ActivityLogComment
    # - 11 Update ActivityLogComment
    # - 12 Create VersionLog
    # The last 2 are for rendering the payload to Cinder like CinderAddon:
    # - 13 Fetch Addon authors
    # - 14 Fetch Promoted Addon
    expected_queries_for_report = 14
    expected_queue_suffix = 'addon-infringement'

    def test_queue(self):
        super().test_queue()
        # For this class the property should be guaranteed to be static.
        assert self.cinder_class.queue == 'amo-env-addon-infringement'

    def test_queue_theme(self):
        # Contrary to reports handled by Cinder moderators, for reports handled
        # by AMO reviewers the queue should remain the same regardless of the
        # addon-type.
        target = self._create_dummy_target(type=amo.ADDON_STATICTHEME)
        cinder_entity = self.cinder_class(target)
        assert cinder_entity.queue_suffix == self.expected_queue_suffix
        assert (
            cinder_entity.queue
            == f'{settings.CINDER_QUEUE_PREFIX}{cinder_entity.queue_suffix}'
        )

    def setUp(self):
        user_factory(id=settings.TASK_USER_ID)

    def test_report(self):
        addon = self._create_dummy_target()
        # Make sure this is testing the case where no user is set (we fall back
        # to the task user).
        assert core.get_user() is None
        addon.current_version.file.update(is_signed=True)
        # Trigger switch_is_active to ensure it's cached to make db query
        # count more predictable.
        waffle.switch_is_active('dsa-abuse-reports-review')
        self._test_report(addon)
        assert (
            addon.current_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        )
        assert ActivityLog.objects.for_versions(addon.current_version).filter(
            action=amo.LOG.NEEDS_HUMAN_REVIEW_CINDER.id
        )

    @override_switch('dsa-abuse-reports-review', active=False)
    def test_report_waffle_switch_off(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        # Trigger switch_is_active to ensure it's cached to make db query
        # count more predictable.
        waffle.switch_is_active('dsa-abuse-reports-review')
        # We are no longer doing the queries for the activitylog, needshumanreview
        # etc since the waffle switch is off. So we're back to the same number of
        # queries made by the reports that go to Cinder.
        self.expected_queries_for_report = TestCinderAddon.expected_queries_for_report
        self._test_report(addon)
        assert addon.current_version.needshumanreview_set.count() == 0

    def test_report_with_version(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        other_version = version_factory(
            addon=addon,
            file_kw={'is_signed': True, 'status': amo.STATUS_AWAITING_REVIEW},
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_report',
            json={'job_id': '1234-xyz'},
            status=201,
        )
        abuse_report = AbuseReport.objects.create(
            guid=addon.guid, addon_version=other_version.version
        )
        report = CinderReport(abuse_report)
        cinder_instance = self.cinder_class(addon, other_version)
        assert cinder_instance.report(report=report, reporter=None)
        assert cinder_instance.report(report=report, reporter=None)
        assert not addon.current_version.needshumanreview_set.exists()
        # We called report() multiple times but there should be only one
        # needs human review instance.
        assert (
            other_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.ABUSE_ADDON_VIOLATION
        )

    def test_appeal_anonymous(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        self._test_appeal(
            CinderUnauthenticatedReporter('itsme', 'm@r.io'), self.cinder_class(addon)
        )
        assert (
            addon.current_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL
        )

    def test_appeal_logged_in(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        self._test_appeal(CinderUser(user_factory()), self.cinder_class(addon))
        assert (
            addon.current_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASONS.ADDON_REVIEW_APPEAL
        )

    @override_switch('dsa-appeals-review', active=False)
    def test_appeal_waffle_switch_off(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        # We are no longer doing the queries for the activitylog, needshumanreview
        # etc since the waffle switch is off. So we're back to the same number of
        # queries made by the reports that go to Cinder.
        self.expected_queries_for_report = TestCinderAddon.expected_queries_for_report
        self._test_appeal(CinderUser(user_factory()), self.cinder_class(addon))
        assert addon.current_version.needshumanreview_set.count() == 0

    def test_create_decision(self):
        target = self._create_dummy_target()

        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'uuid': '123'},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}create_decision',
            json={'error': 'reason'},
            status=400,
        )
        cinder_instance = self.cinder_class(target)
        assert (
            cinder_instance.create_decision(
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value,
                reasoning='some review text',
                policy_uuids=['12345678'],
            )
            == '123'
        )
        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['enforcement_actions_slugs'] == ['amo-reject-version-addon']
        assert request_body['enforcement_actions_update_strategy'] == 'set'
        assert request_body['policy_uuids'] == ['12345678']
        assert request_body['reasoning'] == 'some review text'
        assert request_body['entity']['id'] == str(target.id)

        # Last response is a 400, we raise for that.
        with self.assertRaises(ConnectionError):
            cinder_instance.create_decision(
                action='something',
                reasoning='some review text',
                policy_uuids=['12345678'],
            )

    def test_create_job_decision(self):
        target = self._create_dummy_target()
        job = CinderJob.objects.create(job_id='1234')

        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job.job_id}/decision',
            json={'uuid': '123'},
            status=201,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job.job_id}/decision',
            json={'error': 'reason'},
            status=400,
        )
        cinder_instance = self.cinder_class(target)
        assert (
            cinder_instance.create_job_decision(
                job_id=job.job_id,
                action=DECISION_ACTIONS.AMO_REJECT_VERSION_ADDON.api_value,
                reasoning='some review text',
                policy_uuids=['12345678'],
            )
            == '123'
        )
        request = responses.calls[0].request
        request_body = json.loads(request.body)
        assert request_body['enforcement_actions_slugs'] == ['amo-reject-version-addon']
        assert request_body['enforcement_actions_update_strategy'] == 'set'
        assert request_body['policy_uuids'] == ['12345678']
        assert request_body['reasoning'] == 'some review text'
        assert 'entity' not in request_body

        # Last response is a 400, we raise for that.
        with self.assertRaises(ConnectionError):
            cinder_instance.create_job_decision(
                job_id=job.job_id,
                action='something',
                reasoning='some review text',
                policy_uuids=['12345678'],
            )

    def test_close_job(self):
        target = self._create_dummy_target()
        job_id = '123'
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job_id}/cancel',
            json={'external_id': job_id},
            status=200,
        )
        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}jobs/{job_id}/cancel',
            json={'error': 'reason'},
            status=400,
        )
        cinder_instance = self.cinder_class(target)
        assert cinder_instance.close_job(job_id=job_id) == job_id


class TestCinderUser(BaseTestCinderCase, TestCase):
    cinder_class = CinderUser
    # 2 queries expected:
    # - Related add-ons
    # - Number of listed add-ons
    expected_queries_for_report = 2
    expected_queue_suffix = 'users'

    def _create_dummy_target(self, **kwargs):
        return user_factory(**kwargs)

    def test_build_report_payload(self):
        user = self._create_dummy_target(
            biography='Bîo',
            location='Deep space',
            occupation='Blah',
            homepage='http://home.example.com',
        )
        message = ' bad person!'
        cinder_user = self.cinder_class(user)
        encoded_message = cinder_user.get_str(message)
        abuse_report = AbuseReport.objects.create(user=user, message=message)

        data = cinder_user.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data == {
            'queue_slug': 'amo-env-users',
            'entity_type': 'amo_user',
            'entity': {
                'id': str(user.pk),
                'average_rating': None,
                'biography': user.biography,
                'created': str(user.created),
                'email': user.email,
                'fxa_id': user.fxa_id,
                'homepage': user.homepage,
                'location': user.location,
                'name': user.display_name,
                'num_addons_listed': 0,
                'occupation': user.occupation,
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    }
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(user.pk),
                        'target_type': 'amo_user',
                    }
                ],
            },
        }

        # if we have an email or name
        name = 'Foxy McFox'
        email = 'foxy@mozilla'
        data = cinder_user.build_report_payload(
            report=CinderReport(abuse_report),
            reporter=CinderUnauthenticatedReporter(name, email),
        )
        assert data['context'] == {
            'entities': [
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': encoded_message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
                {
                    'entity_type': 'amo_unauthenticated_reporter',
                    'attributes': {
                        'id': f'{name} : {email}',
                        'name': name,
                        'email': email,
                    },
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(user.pk),
                    'target_type': 'amo_user',
                },
                {
                    'source_id': f'{name} : {email}',
                    'source_type': 'amo_unauthenticated_reporter',
                    'target_id': str(abuse_report.id),
                    'target_type': 'amo_report',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }

        # and if the reporter is authenticated
        reporter_user = user_factory()
        data = cinder_user.build_report_payload(
            report=CinderReport(abuse_report), reporter=CinderUser(reporter_user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': encoded_message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(reporter_user.pk),
                        'created': str(reporter_user.created),
                        'name': reporter_user.display_name,
                        'email': reporter_user.email,
                        'fxa_id': reporter_user.fxa_id,
                    },
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(user.pk),
                    'target_type': 'amo_user',
                },
                {
                    'source_id': str(reporter_user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(abuse_report.pk),
                    'target_type': 'amo_report',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }

    def test_build_report_payload_with_author_and_reporter_being_the_same(self):
        user = self._create_dummy_target()
        addon = addon_factory(users=[user])
        cinder_user = self.cinder_class(user)
        message = 'I dont like this guy'
        encoded_message = cinder_user.get_str(message)
        abuse_report = AbuseReport.objects.create(user=user, message=message)

        data = cinder_user.build_report_payload(
            report=CinderReport(abuse_report), reporter=CinderUser(user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_addon',
                    'attributes': {
                        'id': str(addon.pk),
                        'average_daily_users': addon.average_daily_users,
                        'created': str(addon.created),
                        'guid': addon.guid,
                        'last_updated': str(addon.last_updated),
                        'name': str(addon.name),
                        'promoted': '',
                        'slug': addon.slug,
                        'summary': str(addon.summary),
                    },
                },
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': encoded_message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(user.pk),
                        'created': str(user.created),
                        'name': user.display_name,
                        'email': user.email,
                        'fxa_id': user.fxa_id,
                    },
                },
            ],
            'relationships': [
                {
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                },
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(user.pk),
                    'target_type': 'amo_user',
                },
                {
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(abuse_report.pk),
                    'target_type': 'amo_report',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }

    def test_build_report_payload_addon_author(self):
        user = self._create_dummy_target()
        addon = addon_factory(users=[user])
        cinder_user = self.cinder_class(user)
        message = '@bad person!'
        encoded_message = cinder_user.get_str(message)
        abuse_report = AbuseReport.objects.create(user=user, message=message)

        data = cinder_user.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_addon',
                    'attributes': {
                        'id': str(addon.pk),
                        'average_daily_users': addon.average_daily_users,
                        'created': str(addon.created),
                        'guid': addon.guid,
                        'last_updated': str(addon.last_updated),
                        'name': str(addon.name),
                        'promoted': '',
                        'slug': addon.slug,
                        'summary': str(addon.summary),
                    },
                },
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': encoded_message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
            ],
            'relationships': [
                {
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                },
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(user.pk),
                    'target_type': 'amo_user',
                },
            ],
        }

        # and if the reporter is authenticated
        reporter_user = user_factory()
        data = cinder_user.build_report_payload(
            report=CinderReport(abuse_report), reporter=CinderUser(reporter_user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_addon',
                    'attributes': {
                        'id': str(addon.pk),
                        'average_daily_users': addon.average_daily_users,
                        'created': str(addon.created),
                        'guid': addon.guid,
                        'last_updated': str(addon.last_updated),
                        'name': str(addon.name),
                        'promoted': '',
                        'slug': addon.slug,
                        'summary': str(addon.summary),
                    },
                },
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': encoded_message,
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(reporter_user.pk),
                        'created': str(reporter_user.created),
                        'name': reporter_user.display_name,
                        'email': reporter_user.email,
                        'fxa_id': reporter_user.fxa_id,
                    },
                },
            ],
            'relationships': [
                {
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(addon.pk),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                },
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(user.pk),
                    'target_type': 'amo_user',
                },
                {
                    'source_id': str(reporter_user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(abuse_report.pk),
                    'target_type': 'amo_report',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }

    @mock.patch('olympia.abuse.cinder.create_signed_url_for_file_backup')
    @mock.patch('olympia.abuse.cinder.copy_file_to_backup_storage')
    @mock.patch('olympia.abuse.cinder.backup_storage_enabled', lambda: True)
    def test_build_report_payload_with_picture(
        self, copy_file_to_backup_storage_mock, create_signed_url_for_file_backup_mock
    ):
        copy_file_to_backup_storage_mock.return_value = 'some_remote_path.png'
        fake_signed_picture_url = (
            'https://storage.example.com/signed_url.png?some=thing&else=another'
        )
        create_signed_url_for_file_backup_mock.return_value = fake_signed_picture_url
        user = self._create_dummy_target()
        self.root_storage.copy_stored_file(
            get_image_path('sunbird-small.png'), user.picture_path
        )
        user.update(picture_type='image/png')

        message = '=bad person!'
        cinder_user = self.cinder_class(user)
        encoded_message = cinder_user.get_str(message)
        abuse_report = AbuseReport.objects.create(user=user, message=message)

        data = cinder_user.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data == {
            'queue_slug': 'amo-env-users',
            'entity_type': 'amo_user',
            'entity': {
                'id': str(user.pk),
                'avatar': {
                    'value': fake_signed_picture_url,
                    'mime_type': 'image/png',
                },
                'average_rating': None,
                'biography': '',
                'created': str(user.created),
                'email': user.email,
                'fxa_id': user.fxa_id,
                'homepage': None,
                'location': '',
                'name': user.display_name,
                'num_addons_listed': 0,
                'occupation': '',
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    }
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(user.pk),
                        'target_type': 'amo_user',
                    }
                ],
            },
        }
        assert copy_file_to_backup_storage_mock.call_count == 1
        assert copy_file_to_backup_storage_mock.call_args[0] == (
            user.picture_path,
            user.picture_type,
        )
        assert create_signed_url_for_file_backup_mock.call_count == 1
        assert create_signed_url_for_file_backup_mock.call_args[0] == (
            'some_remote_path.png',
        )

    @mock.patch.object(CinderUser, 'RELATIONSHIPS_BATCH_SIZE', 2)
    def test_build_report_payload_only_includes_first_batch_of_relationships(self):
        user = self._create_dummy_target()
        for _ in range(0, 6):
            user.addons.add(addon_factory())
        cinder_user = self.cinder_class(user)
        message = 'report for lots of relationships'
        abuse_report = AbuseReport.objects.create(user=user, message=message)
        data = cinder_user.build_report_payload(
            report=CinderReport(abuse_report),
            reporter=None,
        )
        # 2 user<->addon (out of 6) + 1 anonymous report
        assert len(data['context']['relationships']) == 3
        assert len(data['context']['entities']) == 3
        first_addon = user.addons.all()[0]
        second_addon = user.addons.all()[1]
        assert data['context'] == {
            'entities': [
                {
                    'attributes': {
                        'average_daily_users': first_addon.average_daily_users,
                        'created': str(first_addon.created),
                        'guid': str(first_addon.guid),
                        'id': str(first_addon.pk),
                        'last_updated': str(first_addon.last_updated),
                        'name': str(first_addon.name),
                        'promoted': '',
                        'slug': str(first_addon.slug),
                        'summary': str(first_addon.summary),
                    },
                    'entity_type': 'amo_addon',
                },
                {
                    'attributes': {
                        'average_daily_users': second_addon.average_daily_users,
                        'created': str(second_addon.created),
                        'guid': str(second_addon.guid),
                        'id': str(second_addon.pk),
                        'last_updated': str(second_addon.last_updated),
                        'name': str(second_addon.name),
                        'promoted': '',
                        'slug': str(second_addon.slug),
                        'summary': str(second_addon.summary),
                    },
                    'entity_type': 'amo_addon',
                },
                {
                    'attributes': {
                        'id': str(abuse_report.pk),
                        'created': str(abuse_report.created),
                        'locale': None,
                        'message': 'report for lots of relationships',
                        'reason': None,
                        'considers_illegal': False,
                    },
                    'entity_type': 'amo_report',
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(first_addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(second_addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'relationship_type': 'amo_report_of',
                    'source_id': str(abuse_report.pk),
                    'source_type': 'amo_report',
                    'target_id': str(user.pk),
                    'target_type': 'amo_user',
                },
            ],
        }

    @mock.patch.object(CinderUser, 'RELATIONSHIPS_BATCH_SIZE', 2)
    def test_report_additional_context(self):
        user = self._create_dummy_target()
        for _ in range(0, 6):
            user.addons.add(addon_factory())
        cinder_user = self.cinder_class(user)

        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}graph/',
            status=202,
        )

        cinder_user.report_additional_context()
        assert len(responses.calls) == 2
        data = json.loads(responses.calls[0].request.body)
        # The first 2 addons should be skipped, they would have been sent with
        # the main report request.
        third_addon = user.addons.all()[2]
        fourth_addon = user.addons.all()[3]
        assert data == {
            'entities': [
                {
                    'attributes': {
                        'average_daily_users': third_addon.average_daily_users,
                        'created': str(third_addon.created),
                        'guid': str(third_addon.guid),
                        'id': str(third_addon.pk),
                        'last_updated': str(third_addon.last_updated),
                        'name': str(third_addon.name),
                        'promoted': '',
                        'slug': str(third_addon.slug),
                        'summary': str(third_addon.summary),
                    },
                    'entity_type': 'amo_addon',
                },
                {
                    'attributes': {
                        'average_daily_users': fourth_addon.average_daily_users,
                        'created': str(fourth_addon.created),
                        'guid': str(fourth_addon.guid),
                        'id': str(fourth_addon.pk),
                        'last_updated': str(fourth_addon.last_updated),
                        'name': str(fourth_addon.name),
                        'promoted': '',
                        'slug': str(fourth_addon.slug),
                        'summary': str(fourth_addon.summary),
                    },
                    'entity_type': 'amo_addon',
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(third_addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(fourth_addon.pk),
                    'target_type': 'amo_addon',
                },
            ],
        }
        data = json.loads(responses.calls[1].request.body)
        fifth_addon = user.addons.all()[4]
        sixth_addon = user.addons.all()[5]
        assert data == {
            'entities': [
                {
                    'attributes': {
                        'average_daily_users': fifth_addon.average_daily_users,
                        'created': str(fifth_addon.created),
                        'guid': str(fifth_addon.guid),
                        'id': str(fifth_addon.pk),
                        'last_updated': str(fifth_addon.last_updated),
                        'name': str(fifth_addon.name),
                        'promoted': '',
                        'slug': str(fifth_addon.slug),
                        'summary': str(fifth_addon.summary),
                    },
                    'entity_type': 'amo_addon',
                },
                {
                    'attributes': {
                        'average_daily_users': sixth_addon.average_daily_users,
                        'created': str(sixth_addon.created),
                        'guid': str(sixth_addon.guid),
                        'id': str(sixth_addon.pk),
                        'last_updated': str(sixth_addon.last_updated),
                        'name': str(sixth_addon.name),
                        'promoted': '',
                        'slug': str(sixth_addon.slug),
                        'summary': str(sixth_addon.summary),
                    },
                    'entity_type': 'amo_addon',
                },
            ],
            'relationships': [
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(fifth_addon.pk),
                    'target_type': 'amo_addon',
                },
                {
                    'relationship_type': 'amo_author_of',
                    'source_id': str(user.pk),
                    'source_type': 'amo_user',
                    'target_id': str(sixth_addon.pk),
                    'target_type': 'amo_addon',
                },
            ],
        }

    @mock.patch.object(CinderUser, 'RELATIONSHIPS_BATCH_SIZE', 2)
    def test_report_additional_context_error(self):
        user = self._create_dummy_target()
        for _ in range(0, 6):
            user.addons.add(addon_factory())
        cinder_user = self.cinder_class(user)

        responses.add(
            responses.POST,
            f'{settings.CINDER_SERVER_URL}graph/',
            status=400,
        )

        with self.assertRaises(ConnectionError):
            cinder_user.report_additional_context()


class TestCinderRating(BaseTestCinderCase, TestCase):
    cinder_class = CinderRating
    expected_queries_for_report = 1  # For the author
    expected_queue_suffix = 'ratings'

    def setUp(self):
        self.user = user_factory()
        self.addon = addon_factory()

    def _create_dummy_target(self, **kwargs):
        return Rating.objects.create(
            addon=self.addon, user=self.user, rating=random.randint(0, 5), **kwargs
        )

    def test_build_report_payload(self):
        rating = self._create_dummy_target()
        cinder_rating = self.cinder_class(rating)
        message = '-bad rating!'
        encoded_message = cinder_rating.get_str(message)
        abuse_report = AbuseReport.objects.create(rating=rating, message=message)

        data = cinder_rating.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data == {
            'queue_slug': 'amo-env-ratings',
            'entity_type': 'amo_rating',
            'entity': {
                'id': str(rating.pk),
                'body': rating.body,
                'created': str(rating.created),
                'score': rating.rating,
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'entity_type': 'amo_user',
                        'attributes': {
                            'id': str(self.user.pk),
                            'created': str(self.user.created),
                            'name': self.user.display_name,
                            'email': self.user.email,
                            'fxa_id': self.user.fxa_id,
                        },
                    },
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    },
                ],
                'relationships': [
                    {
                        'source_id': str(self.user.pk),
                        'source_type': 'amo_user',
                        'target_id': str(rating.pk),
                        'target_type': 'amo_rating',
                        'relationship_type': 'amo_rating_author_of',
                    },
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(rating.pk),
                        'target_type': 'amo_rating',
                    },
                ],
            },
        }

    def test_build_report_payload_with_author_and_reporter_being_the_same(self):
        rating = self._create_dummy_target()
        user = rating.user
        cinder_rating = self.cinder_class(rating)
        message = '@my own words!'
        encoded_message = cinder_rating.get_str(message)
        abuse_report = AbuseReport.objects.create(rating=rating, message=message)

        data = cinder_rating.build_report_payload(
            report=CinderReport(abuse_report), reporter=CinderUser(user)
        )
        assert data == {
            'queue_slug': 'amo-env-ratings',
            'entity_type': 'amo_rating',
            'entity': {
                'id': str(rating.pk),
                'body': rating.body,
                'created': str(rating.created),
                'score': rating.rating,
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'entity_type': 'amo_user',
                        'attributes': {
                            'id': str(user.pk),
                            'created': str(user.created),
                            'name': user.display_name,
                            'email': user.email,
                            'fxa_id': user.fxa_id,
                        },
                    },
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    },
                ],
                'relationships': [
                    {
                        'source_id': str(user.pk),
                        'source_type': 'amo_user',
                        'target_id': str(rating.pk),
                        'target_type': 'amo_rating',
                        'relationship_type': 'amo_rating_author_of',
                    },
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(rating.pk),
                        'target_type': 'amo_rating',
                    },
                    {
                        'source_id': str(user.pk),
                        'source_type': 'amo_user',
                        'target_id': str(abuse_report.pk),
                        'target_type': 'amo_report',
                        'relationship_type': 'amo_reporter_of',
                    },
                ],
            },
        }

    def test_build_report_payload_developer_reply(self):
        addon_author = user_factory()
        self.addon = addon_factory(users=(addon_author,))
        original_rating = Rating.objects.create(
            addon=self.addon, user=self.user, rating=random.randint(0, 5)
        )
        rating = Rating.objects.create(
            addon=self.addon, user=addon_author, reply_to=original_rating
        )
        cinder_rating = self.cinder_class(rating)
        message = '-bad reply!'
        encoded_message = cinder_rating.get_str(message)
        abuse_report = AbuseReport.objects.create(rating=rating, message=message)

        data = cinder_rating.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data == {
            'queue_slug': 'amo-env-ratings',
            'entity_type': 'amo_rating',
            'entity': {
                'id': str(rating.pk),
                'body': rating.body,
                'created': str(rating.created),
                'score': None,
            },
            'reasoning': encoded_message,
            'context': {
                'entities': [
                    {
                        'entity_type': 'amo_user',
                        'attributes': {
                            'id': str(addon_author.id),
                            'created': str(addon_author.created),
                            'name': addon_author.display_name,
                            'email': addon_author.email,
                            'fxa_id': addon_author.fxa_id,
                        },
                    },
                    {
                        'entity_type': 'amo_rating',
                        'attributes': {
                            'id': str(original_rating.pk),
                            'body': original_rating.body,
                            'created': str(original_rating.created),
                            'score': original_rating.rating,
                        },
                    },
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    },
                ],
                'relationships': [
                    {
                        'source_id': str(addon_author.id),
                        'source_type': 'amo_user',
                        'target_id': str(rating.pk),
                        'target_type': 'amo_rating',
                        'relationship_type': 'amo_rating_author_of',
                    },
                    {
                        'source_id': str(original_rating.pk),
                        'source_type': 'amo_rating',
                        'target_id': str(rating.pk),
                        'target_type': 'amo_rating',
                        'relationship_type': 'amo_rating_reply_to',
                    },
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(rating.pk),
                        'target_type': 'amo_rating',
                    },
                ],
            },
        }


class TestCinderCollection(BaseTestCinderCase, TestCase):
    cinder_class = CinderCollection
    expected_queries_for_report = 1  # For the author
    expected_queue_suffix = 'collections'

    def setUp(self):
        self.user = user_factory()

    def _create_dummy_target(self, **kwargs):
        collection = collection_factory(author=self.user)
        addon = addon_factory()
        collection_addon = CollectionAddon.objects.create(
            collection=collection, addon=addon, comments='Fôo'
        )
        with self.activate('fr'):
            collection_addon.comments = 'Bär'
            collection_addon.save()
        CollectionAddon.objects.create(
            collection=collection, addon=addon_factory(), comments='Alice'
        )
        CollectionAddon.objects.create(collection=collection, addon=addon_factory())
        return collection

    def test_build_report_payload(self):
        collection = self._create_dummy_target()
        cinder_collection = self.cinder_class(collection)
        message = '@bad collection!'
        encoded_message = cinder_collection.get_str(message)
        abuse_report = AbuseReport.objects.create(
            collection=collection, message=message
        )

        data = cinder_collection.build_report_payload(
            report=CinderReport(abuse_report), reporter=None
        )
        assert data == {
            'context': {
                'entities': [
                    {
                        'entity_type': 'amo_user',
                        'attributes': {
                            'id': str(self.user.pk),
                            'created': str(self.user.created),
                            'name': self.user.display_name,
                            'email': self.user.email,
                            'fxa_id': self.user.fxa_id,
                        },
                    },
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    },
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_collection_author_of',
                        'source_id': str(self.user.pk),
                        'source_type': 'amo_user',
                        'target_id': str(collection.pk),
                        'target_type': 'amo_collection',
                    },
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(collection.pk),
                        'target_type': 'amo_collection',
                    },
                ],
            },
            'entity': {
                'comments': ['Fôo', 'Bär', 'Alice'],
                'created': str(collection.created),
                'description': str(collection.description),
                'modified': str(collection.modified),
                'id': str(collection.pk),
                'name': str(collection.name),
                'slug': collection.slug,
            },
            'entity_type': 'amo_collection',
            'queue_slug': 'amo-env-collections',
            'reasoning': encoded_message,
        }

    def test_build_report_payload_with_author_and_reporter_being_the_same(self):
        collection = self._create_dummy_target()
        cinder_collection = self.cinder_class(collection)
        user = collection.author
        message = '=Collect me!'
        encoded_message = cinder_collection.get_str(message)
        abuse_report = AbuseReport.objects.create(
            collection=collection, message=message
        )

        data = cinder_collection.build_report_payload(
            report=CinderReport(abuse_report), reporter=CinderUser(user)
        )
        assert data == {
            'context': {
                'entities': [
                    {
                        'entity_type': 'amo_user',
                        'attributes': {
                            'id': str(user.pk),
                            'created': str(user.created),
                            'name': user.display_name,
                            'email': user.email,
                            'fxa_id': user.fxa_id,
                        },
                    },
                    {
                        'attributes': {
                            'id': str(abuse_report.pk),
                            'created': str(abuse_report.created),
                            'locale': None,
                            'message': encoded_message,
                            'reason': None,
                            'considers_illegal': False,
                        },
                        'entity_type': 'amo_report',
                    },
                ],
                'relationships': [
                    {
                        'relationship_type': 'amo_collection_author_of',
                        'source_id': str(self.user.pk),
                        'source_type': 'amo_user',
                        'target_id': str(collection.pk),
                        'target_type': 'amo_collection',
                    },
                    {
                        'relationship_type': 'amo_report_of',
                        'source_id': str(abuse_report.pk),
                        'source_type': 'amo_report',
                        'target_id': str(collection.pk),
                        'target_type': 'amo_collection',
                    },
                    {
                        'source_id': str(user.pk),
                        'source_type': 'amo_user',
                        'target_id': str(abuse_report.pk),
                        'target_type': 'amo_report',
                        'relationship_type': 'amo_reporter_of',
                    },
                ],
            },
            'entity': {
                'comments': ['Fôo', 'Bär', 'Alice'],
                'created': str(collection.created),
                'description': str(collection.description),
                'modified': str(collection.modified),
                'id': str(collection.pk),
                'name': str(collection.name),
                'slug': collection.slug,
            },
            'entity_type': 'amo_collection',
            'queue_slug': 'amo-env-collections',
            'reasoning': encoded_message,
        }


class TestCinderReport(TestCase):
    cinder_class = CinderReport

    def test_reason_in_attributes(self):
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.POLICY_VIOLATION,
        )
        assert self.cinder_class(abuse_report).get_attributes() == {
            'id': str(abuse_report.pk),
            'created': str(abuse_report.created),
            'locale': None,
            'message': '',
            'reason': "DSA: It violates Mozilla's Add-on Policies",
            'considers_illegal': False,
        }

    def test_locale_in_attributes(self):
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid, application_locale='en_US'
        )
        assert self.cinder_class(abuse_report).get_attributes() == {
            'id': str(abuse_report.pk),
            'created': str(abuse_report.created),
            'locale': 'en_US',
            'message': '',
            'reason': None,
            'considers_illegal': False,
        }

    def test_considers_illegal(self):
        abuse_report = AbuseReport.objects.create(
            guid=addon_factory().guid,
            reason=AbuseReport.REASONS.ILLEGAL,
        )
        assert self.cinder_class(abuse_report).get_attributes() == {
            'id': str(abuse_report.pk),
            'created': str(abuse_report.created),
            'locale': None,
            'message': '',
            'reason': (
                'DSA: It violates the law or contains content that violates the law'
            ),
            'considers_illegal': True,
        }
