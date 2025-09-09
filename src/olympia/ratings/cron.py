from olympia.ratings.tasks import flag_high_rating_addons_according_to_review_tier


def flag_high_rating_addons():
    flag_high_rating_addons_according_to_review_tier.delay()
