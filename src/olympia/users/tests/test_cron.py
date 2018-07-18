# -*- coding: utf-8 -*-
from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.ratings.models import Rating
from olympia.users.cron import update_user_ratings


class TestUpdateUserRatings(TestCase):
    def test_update_user_ratings(self):
        developer_a = user_factory()
        developer_b = user_factory()
        developer_c = user_factory()
        addon1 = addon_factory(users=[developer_a, developer_b])
        addon2 = addon_factory(users=[developer_a])
        addon3 = addon_factory(users=[developer_b])
        addon_deleted = addon_factory(users=[developer_a, developer_c])
        version_deleted = addon_deleted.current_version
        addon_deleted.delete()

        Rating.objects.create(
            rating=4,
            addon=addon1,
            version=addon1.current_version,
            user=user_factory(),
        )
        Rating.objects.create(
            rating=5,
            addon=addon1,
            version=addon1.current_version,
            user=user_factory(),
        )
        Rating.objects.create(
            rating=3,
            addon=addon2,
            version=addon2.current_version,
            user=user_factory(),
        )
        Rating.objects.create(
            rating=5,
            addon=addon_deleted,
            version=version_deleted,
            user=user_factory(),
        )  # Should be ignored.
        Rating.objects.create(
            rating=0,
            addon=addon3,
            version=addon3.current_version,
            user=user_factory(),
        )  # Should be ignored.

        update_user_ratings()

        developer_a.reload()
        developer_b.reload()
        developer_c.reload()

        assert developer_a.averagerating == 4.0  # (4+5+3) / 3.
        assert developer_b.averagerating == 4.5  # (4+5) / 2.
        assert developer_c.averagerating is None
