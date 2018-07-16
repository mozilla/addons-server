import requests

from django.conf import settings
from django.db import models

import olympia.core.logger
from olympia.amo.models import ModelBase


log = olympia.core.logger.getLogger('z.lib.akismet')


class AkismetReport(ModelBase):
    UNKNOWN = -1
    HAM = 0
    DEFINITE_SPAM = 1
    MAYBE_SPAM = 2
    RESULT_CHOICES = (
        (UNKNOWN, 'Unknown'),
        (HAM, 'Ham'),
        (DEFINITE_SPAM, 'Definite Spam'),
        (MAYBE_SPAM, 'Maybe Spam'))
    HEADERS = {'User-Agent': 'Mozilla Addons/3.0'}

    # The following should normally be set before comment_check()
    comment_type = models.CharField(max_length=255)
    user_ip = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255)
    referrer = models.CharField(max_length=255)
    user_name = models.CharField(max_length=255)
    user_email = models.CharField(max_length=255)
    comment = models.TextField()
    comment_modified = models.DateTimeField()
    content_link = models.CharField(max_length=255)
    content_modified = models.DateTimeField()

    # Non-comment properties:
    result = models.PositiveSmallIntegerField(
        null=True, choices=RESULT_CHOICES)
    reported = models.BooleanField(default=False)

    # Fks to the supported types of content we support submitting
    # Just Rating at first
    rating_instance = models.ForeignKey(
        'ratings.Rating', related_name='+', null=True,
        on_delete=models.SET_NULL)

    class Meta:
        db_table = 'akismet_reports'

    def _get_data(self):
        data = {
            'blog': settings.SITE_URL,
            'user_ip': self.user_ip,
            'user_agent': self.user_agent,
            'referrer': self.referrer,
            'permalink': self.content_link,
            'comment_type': self.comment_type,
            'comment_author': self.user_name,
            'comment_author_email': self.user_email,
            # 'comment_author_url': '',
            'comment_content': self.comment,
            'comment_date_gmt': self.comment_modified,
            'comment_post_modified_gmt': self.content_modified,

            # 'blog_lang' : get_language(),
            'blog_charset': 'utf-8',
            # 'user_role': 'administrator' if user.is_staff else ''
            'is_test': not settings.AKISMET_REAL_SUBMIT,
        }
        return {key: value for key, value in data.items() if value is not None}

    def comment_check(self):
        url = settings.AKISMET_API_URL.format(
            api_key=settings.AKISMET_API_KEY, action='comment-check')
        response = requests.post(
            url, data=self._get_data(), headers=self.HEADERS,
            timeout=settings.AKISMET_API_TIMEOUT)
        try:
            outcome = response.json()
            discard = response.headers.get('X-akismet-pro-tip') == 'discard'
            if outcome is True or outcome is False:
                self.update(result=(
                    self.HAM if not outcome else
                    self.DEFINITE_SPAM if discard else self.MAYBE_SPAM))
                return self.result
            # If outcome isn't True or False it's invalid.
        except ValueError:
            pass
        log.error(
            'Akismet error %s' % (
                response.headers.get('X-akismet-debug-help') or response.text))
        self.update(result=self.UNKNOWN)
        return self.result

    @classmethod
    def create_for_rating(cls, rating, user_agent, referrer):
        instance = cls.objects.create(
            rating_instance=rating,
            comment_type='user-review',
            user_ip=rating.ip_address,
            user_agent=user_agent,
            referrer=referrer,
            user_name=rating.user.name,
            user_email=rating.user.email,
            content_link=rating.addon.get_url_path(),
            content_modified=rating.addon.last_updated,
            comment=rating.body,
            comment_modified=rating.modified,
        )
        return instance
