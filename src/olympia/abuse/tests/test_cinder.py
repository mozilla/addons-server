from django.conf import settings

import responses

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory, version_factory
from olympia.ratings.models import Rating
from olympia.reviewers.models import NeedsHumanReview

from ..cinder import (
    CinderAddon,
    CinderAddonByReviewers,
    CinderRating,
    CinderUnauthenticatedReporter,
    CinderUser,
)


class BaseTestCinderCase:
    cinder_class = None  # Override in child classes

    def _create_dummy_target(self, **kwargs):
        raise NotImplementedError

    def _test_report(self, cinder_instance):
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
        assert (
            cinder_instance.report(report_text='reason', category=None, reporter=None)
            == '1234-xyz'
        )
        assert (
            cinder_instance.report(
                report_text='reason', category=None, reporter=CinderUser(user_factory())
            )
            == '1234-xyz'
        )
        assert (
            cinder_instance.report(
                report_text='reason',
                category=None,
                reporter=CinderUnauthenticatedReporter(name='name', email='e@ma.il'),
            )
            == '1234-xyz'
        )
        with self.assertRaises(ConnectionError):
            cinder_instance.report(report_text='reason', category=None, reporter=None)

    def test_build_report_payload(self):
        raise NotImplementedError

    def test_report(self):
        self._test_report(self.cinder_class(self._create_dummy_target()))

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
                decision_id=fake_decision_id, appeal_text='reason', appealer=appealer
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
                decision_id=fake_decision_id, appeal_text='reason', appealer=appealer
            )

    def test_appeal_anonymous(self):
        self._test_appeal(CinderUser(user_factory()))

    def test_appeal_logged_in(self):
        self._test_appeal(CinderUnauthenticatedReporter('itsme', 'm@r.io'))


class TestCinderAddon(BaseTestCinderCase, TestCase):
    cinder_class = CinderAddon

    def _create_dummy_target(self, **kwargs):
        return addon_factory(**kwargs)

    def test_build_report_payload(self):
        addon = self._create_dummy_target()
        reason = 'bad addon!'
        cinder_addon = self.cinder_class(addon)

        data = cinder_addon.build_report_payload(
            report_text=reason, category=None, reporter=None
        )
        assert data == {
            'queue_slug': self.cinder_class.queue,
            'entity_type': 'amo_addon',
            'entity': {
                'id': str(addon.id),
                'guid': addon.guid,
                'slug': addon.slug,
                'name': str(addon.name),
            },
            'reasoning': reason,
            'context': {'entities': [], 'relationships': []},
        }

        # if we have an email or name
        name = 'Foxy McFox'
        email = 'foxy@mozilla'
        data = cinder_addon.build_report_payload(
            report_text=reason,
            category=None,
            reporter=CinderUnauthenticatedReporter(name, email),
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_unauthenticated_reporter',
                    'attributes': {
                        'id': f'{name} : {email}',
                        'name': name,
                        'email': email,
                    },
                }
            ],
            'relationships': [
                {
                    'source_id': f'{name} : {email}',
                    'source_type': 'amo_unauthenticated_reporter',
                    'target_id': str(addon.id),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_reporter_of',
                }
            ],
        }

        # and if the reporter is authenticated
        reporter_user = user_factory()
        data = cinder_addon.build_report_payload(
            report_text=reason, category=None, reporter=CinderUser(reporter_user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(reporter_user.id),
                        'name': reporter_user.display_name,
                        'email': reporter_user.email,
                        'fxa_id': reporter_user.fxa_id,
                    },
                }
            ],
            'relationships': [
                {
                    'source_id': str(reporter_user.id),
                    'source_type': 'amo_user',
                    'target_id': str(addon.id),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_reporter_of',
                }
            ],
        }

    def test_build_report_payload_with_author(self):
        author = user_factory()
        addon = self._create_dummy_target(users=[author])
        reason = 'bad addon!'
        cinder_addon = self.cinder_class(addon)

        data = cinder_addon.build_report_payload(
            report_text=reason, category=None, reporter=None
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(author.id),
                        'name': author.display_name,
                        'email': author.email,
                        'fxa_id': author.fxa_id,
                    },
                }
            ],
            'relationships': [
                {
                    'source_id': str(author.id),
                    'source_type': 'amo_user',
                    'target_id': str(addon.id),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                }
            ],
        }

        # and if the reporter is authenticated
        reporter_user = user_factory()
        data = cinder_addon.build_report_payload(
            report_text=reason, category=None, reporter=CinderUser(reporter_user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(author.id),
                        'name': author.display_name,
                        'email': author.email,
                        'fxa_id': author.fxa_id,
                    },
                },
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(reporter_user.id),
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
                    'target_id': str(addon.id),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                },
                {
                    'source_id': str(reporter_user.id),
                    'source_type': 'amo_user',
                    'target_id': str(addon.id),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }


class TestCinderAddonByReviewers(TestCinderAddon):
    cinder_class = CinderAddonByReviewers

    def setUp(self):
        user_factory(id=settings.TASK_USER_ID)

    def test_report(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        self._test_report(self.cinder_class(addon))
        assert (
            addon.current_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_ABUSE_ADDON_VIOLATION
        )

    def test_report_with_version(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        other_version = version_factory(
            addon=addon,
            file_kw={'is_signed': True, 'status': amo.STATUS_AWAITING_REVIEW},
        )
        self._test_report(self.cinder_class(addon, other_version))
        assert not addon.current_version.needshumanreview_set.exists()
        # that there's only one is required - _test_report calls report() multiple times
        assert (
            other_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_ABUSE_ADDON_VIOLATION
        )

    def test_appeal_anonymous(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        self._test_appeal(
            CinderUnauthenticatedReporter('itsme', 'm@r.io'), self.cinder_class(addon)
        )
        assert (
            addon.current_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_ABUSE_ADDON_VIOLATION_APPEAL
        )

    def test_appeal_logged_in(self):
        addon = self._create_dummy_target()
        addon.current_version.file.update(is_signed=True)
        self._test_appeal(CinderUser(user_factory()), self.cinder_class(addon))
        assert (
            addon.current_version.needshumanreview_set.get().reason
            == NeedsHumanReview.REASON_ABUSE_ADDON_VIOLATION_APPEAL
        )


class TestCinderUser(BaseTestCinderCase, TestCase):
    cinder_class = CinderUser

    def _create_dummy_target(self, **kwargs):
        return user_factory(**kwargs)

    def test_build_report_payload(self):
        user = self._create_dummy_target()
        reason = 'bad person!'
        cinder_user = self.cinder_class(user)

        data = cinder_user.build_report_payload(
            report_text=reason, category=None, reporter=None
        )
        assert data == {
            'queue_slug': self.cinder_class.queue,
            'entity_type': 'amo_user',
            'entity': {
                'id': str(user.id),
                'name': user.display_name,
                'email': user.email,
                'fxa_id': user.fxa_id,
            },
            'reasoning': reason,
            'context': {'entities': [], 'relationships': []},
        }

        # if we have an email or name
        name = 'Foxy McFox'
        email = 'foxy@mozilla'
        data = cinder_user.build_report_payload(
            report_text=reason,
            category=None,
            reporter=CinderUnauthenticatedReporter(name, email),
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_unauthenticated_reporter',
                    'attributes': {
                        'id': f'{name} : {email}',
                        'name': name,
                        'email': email,
                    },
                }
            ],
            'relationships': [
                {
                    'source_id': f'{name} : {email}',
                    'source_type': 'amo_unauthenticated_reporter',
                    'target_id': str(user.id),
                    'target_type': 'amo_user',
                    'relationship_type': 'amo_reporter_of',
                }
            ],
        }

        # and if the reporter is authenticated
        reporter_user = user_factory()
        data = cinder_user.build_report_payload(
            report_text=reason, category=None, reporter=CinderUser(reporter_user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(reporter_user.id),
                        'name': reporter_user.display_name,
                        'email': reporter_user.email,
                        'fxa_id': reporter_user.fxa_id,
                    },
                }
            ],
            'relationships': [
                {
                    'source_id': str(reporter_user.id),
                    'source_type': 'amo_user',
                    'target_id': str(user.id),
                    'target_type': 'amo_user',
                    'relationship_type': 'amo_reporter_of',
                }
            ],
        }

    def test_build_report_payload_addon_author(self):
        user = self._create_dummy_target()
        addon = addon_factory(users=[user])
        cinder_user = self.cinder_class(user)
        reason = 'bad person!'

        data = cinder_user.build_report_payload(
            report_text=reason, category=None, reporter=None
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_addon',
                    'attributes': {
                        'id': str(addon.id),
                        'guid': addon.guid,
                        'slug': addon.slug,
                        'name': str(addon.name),
                    },
                }
            ],
            'relationships': [
                {
                    'source_id': str(user.id),
                    'source_type': 'amo_user',
                    'target_id': str(addon.id),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                }
            ],
        }

        # and if the reporter is authenticated
        reporter_user = user_factory()
        data = cinder_user.build_report_payload(
            report_text=reason, category=None, reporter=CinderUser(reporter_user)
        )
        assert data['context'] == {
            'entities': [
                {
                    'entity_type': 'amo_addon',
                    'attributes': {
                        'id': str(addon.id),
                        'guid': addon.guid,
                        'slug': addon.slug,
                        'name': str(addon.name),
                    },
                },
                {
                    'entity_type': 'amo_user',
                    'attributes': {
                        'id': str(reporter_user.id),
                        'name': reporter_user.display_name,
                        'email': reporter_user.email,
                        'fxa_id': reporter_user.fxa_id,
                    },
                },
            ],
            'relationships': [
                {
                    'source_id': str(user.id),
                    'source_type': 'amo_user',
                    'target_id': str(addon.id),
                    'target_type': 'amo_addon',
                    'relationship_type': 'amo_author_of',
                },
                {
                    'source_id': str(reporter_user.id),
                    'source_type': 'amo_user',
                    'target_id': str(user.id),
                    'target_type': 'amo_user',
                    'relationship_type': 'amo_reporter_of',
                },
            ],
        }


class TestCinderRating(BaseTestCinderCase, TestCase):
    cinder_class = CinderRating

    def setUp(self):
        self.user = user_factory()
        self.addon = addon_factory()

    def _create_dummy_target(self, **kwargs):
        return Rating.objects.create(addon=self.addon, user=self.user, **kwargs)

    def test_build_report_payload(self):
        rating = self._create_dummy_target()
        cinder_rating = self.cinder_class(rating)
        reason = 'bad rating!'

        data = cinder_rating.build_report_payload(
            report_text=reason, category=None, reporter=None
        )
        assert data == {
            'queue_slug': 'amo-content-infringement',
            'entity_type': 'amo_rating',
            'entity': {
                'id': str(rating.id),
                'body': rating.body,
            },
            'reasoning': reason,
            'context': {
                'entities': [
                    {
                        'entity_type': 'amo_user',
                        'attributes': {
                            'id': str(self.user.id),
                            'name': self.user.display_name,
                            'email': self.user.email,
                            'fxa_id': self.user.fxa_id,
                        },
                    }
                ],
                'relationships': [
                    {
                        'source_id': str(self.user.id),
                        'source_type': 'amo_user',
                        'target_id': str(rating.id),
                        'target_type': 'amo_rating',
                        'relationship_type': 'amo_rating_author_of',
                    }
                ],
            },
        }
