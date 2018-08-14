# -*- coding: utf-8 -*-
from datetime import datetime

from django.conf import settings

import responses

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.ratings.models import Rating

from .models import AkismetReport


class TestAkismetReportsModel(TestCase):

    def test_create_for_rating(self):
        user = user_factory(homepage='https://spam.spam/')
        addon = addon_factory()
        rating = Rating.objects.create(
            addon=addon, user=user, rating=4, body='spám?',
            ip_address='1.23.45.67')
        ua = 'foo/baa'
        referrer = 'https://mozilla.org/'
        report = AkismetReport.create_for_rating(rating, ua, referrer)

        assert report.rating_instance == rating
        data = report._get_data()
        assert data == {
            'blog': settings.SITE_URL,
            'user_ip': rating.ip_address,
            'user_agent': ua,
            'referrer': referrer,
            'permalink': addon.get_url_path(),
            'comment_type': 'user-review',
            'comment_author': user.username,
            'comment_author_email': user.email,
            'comment_author_url': user.homepage,
            'comment_content': rating.body,
            'comment_date_gmt': rating.modified,
            'comment_post_modified_gmt': addon.last_updated,
            'blog_charset': 'utf-8',
            'is_test': not settings.AKISMET_REAL_SUBMIT,
        }

    def _create_report(self, kws=None):
        defaults = dict(
            comment_type='user-review',
            user_ip='9.8.7.6.5',
            user_agent='Agent Bond',
            referrer='á4565',
            user_name='steve',
            user_email='steve@steve.com',
            user_homepage='http://spam.spam',
            content_link='https://addons.mozilla.org',
            content_modified=datetime.now(),
            comment='spammy McSpam?',
            comment_modified=datetime.now(),
        )
        if kws:
            defaults.update(**kws)
        instance = AkismetReport.objects.create(**defaults)
        return instance

    def test_comment_check(self):
        report = self._create_report()

        url = settings.AKISMET_API_URL.format(
            api_key=settings.AKISMET_API_KEY, action='comment-check')
        responses.add(responses.POST, url, json=True)
        responses.add(
            responses.POST, url, json=True,
            headers={'X-akismet-pro-tip': 'discard'})
        # Headers should be ignored on False but add anyway.
        responses.add(
            responses.POST, url, json=False,
            headers={'X-akismet-pro-tip': 'discard'})

        result = report.comment_check()
        assert result == report.result == AkismetReport.MAYBE_SPAM

        result = report.comment_check()
        assert result == report.result == AkismetReport.DEFINITE_SPAM

        result = report.comment_check()
        assert result == report.result == AkismetReport.HAM
