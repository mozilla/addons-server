from nose.tools import eq_

import amo.tests

import mkt.constants.ratingsbodies as ratingsbodies


class TestRatingsBodies(amo.tests.TestCase):

    def test_all_ratings_waffle_off(self):
        ratings = ratingsbodies.ALL_RATINGS()

        # Assert only CLASSIND and GENERIC ratings are present.
        assert ratingsbodies.CLASSIND_L in ratings
        assert ratingsbodies.GENERIC_3 in ratings
        assert ratingsbodies.ESRB_E not in ratings
        assert ratingsbodies.PEGI_3 not in ratings
        assert ratingsbodies.USK_0 not in ratings

    def test_all_ratings_waffle_on(self):
        self.create_switch('iarc')
        ratings = ratingsbodies.ALL_RATINGS()

        # Assert all ratings bodies are present.
        assert ratingsbodies.CLASSIND_L in ratings
        assert ratingsbodies.GENERIC_3 in ratings
        assert ratingsbodies.ESRB_E in ratings
        assert ratingsbodies.PEGI_3 in ratings
        assert ratingsbodies.USK_0 in ratings

    def test_ratings_by_name_waffle(self):
        without_waffle = ratingsbodies.RATINGS_BY_NAME()

        self.create_switch('iarc', db=True)
        with_waffle = ratingsbodies.RATINGS_BY_NAME()

        # Test waffle off excludes ratings.
        assert len(without_waffle) < len(with_waffle)

    def test_ratings_by_name_lazy_translation(self):
        generic_3_choice = ratingsbodies.RATINGS_BY_NAME()[6]
        eq_(generic_3_choice[1], 'Generic - For ages 3+')

    def test_ratings_has_ratingsbody(self):
        eq_(ratingsbodies.GENERIC_3.ratingsbody, ratingsbodies.GENERIC)
        eq_(ratingsbodies.CLASSIND_L.ratingsbody, ratingsbodies.CLASSIND)
        eq_(ratingsbodies.ESRB_E.ratingsbody, ratingsbodies.ESRB)
        eq_(ratingsbodies.USK_0.ratingsbody, ratingsbodies.USK)
        eq_(ratingsbodies.PEGI_3.ratingsbody, ratingsbodies.PEGI)

    def test_dehydrate_rating(self):
        self.create_switch('iarc')

        for rating in ratingsbodies.ALL_RATINGS():
            rating = ratingsbodies.dehydrate_rating(rating)
            assert isinstance(rating.name, unicode)
            assert rating.label
            assert isinstance(rating.description, unicode)

    def test_dehydrate_ratings_body(self):
        self.create_switch('iarc')

        for k, body in ratingsbodies.RATINGS_BODIES.iteritems():
            body = ratingsbodies.dehydrate_ratings_body(body)
            assert isinstance(body.name, unicode)
            assert body.label
            assert isinstance(body.description, unicode)
