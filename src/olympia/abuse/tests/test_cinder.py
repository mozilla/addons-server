from olympia.amo.tests import TestCase, addon_factory, user_factory

from ..cinder import CinderAddon, CinderUser


class TestCinderAddon(TestCase):
    def test_build_report_payload(self):
        addon = addon_factory()
        reason = 'bad addon!'
        cinder_addon = CinderAddon(addon)

        data = cinder_addon.build_report_payload(reason, None)
        assert data == {
            'queue_slug': 'amo-content-infringement',
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

        # and if the reporter isn't anonymous
        reporter_user = user_factory()
        data = cinder_addon.build_report_payload(reason, CinderUser(reporter_user))
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
        addon = addon_factory(users=[author])
        reason = 'bad addon!'
        cinder_addon = CinderAddon(addon)

        data = cinder_addon.build_report_payload(reason, None)
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

        # and if the reporter isn't anonymous
        reporter_user = user_factory()
        data = cinder_addon.build_report_payload(reason, CinderUser(reporter_user))
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


class TestCinderUser(TestCase):
    def test_build_report_payload(self):
        user = user_factory()
        reason = 'bad person!'
        cinder_user = CinderUser(user)

        data = cinder_user.build_report_payload(reason, None)
        assert data == {
            'queue_slug': 'amo-content-infringement',
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
        # and if the reporter isn't anonymous
        reporter_user = user_factory()
        data = cinder_user.build_report_payload(reason, CinderUser(reporter_user))
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
        user = user_factory()
        addon = addon_factory(users=[user])
        cinder_user = CinderUser(user)
        reason = 'bad person!'

        data = cinder_user.build_report_payload(reason, None)
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

        # and if the reporter isn't anonymous
        reporter_user = user_factory()
        data = cinder_user.build_report_payload(reason, CinderUser(reporter_user))
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
