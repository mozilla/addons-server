from unittest import mock

from django.core.management import call_command


@mock.patch('olympia.ratings.tasks.flag_high_rating_addons_according_to_review_tier')
def test_flag_high_ratings(flag_high_rating_addons_mock):
    call_command('cron', 'flag_high_rating_addons')
    assert flag_high_rating_addons_mock.delay.call_count == 1    
