import requests

from django.conf import settings
from django.db import models

from django_statsd.clients import statsd

import olympia.core.logger
from olympia.amo.models import ModelBase


log = olympia.core.logger.getLogger('z.lib.akismet')


class AkismetReport(ModelBase):
    HAM = 0
    DEFINITE_SPAM = 1
    MAYBE_SPAM = 2
    UNKNOWN = 3
    RESULT_CHOICES = (
        (UNKNOWN, 'Unknown'),
        (HAM, 'Ham'),
        (DEFINITE_SPAM, 'Definite Spam'),
        (MAYBE_SPAM, 'Maybe Spam'))
    HEADERS = {'User-Agent': 'Mozilla Addons/3.0'}
    METRIC_LOOKUP = {
        UNKNOWN: 'fail',
        HAM: 'ham',
        DEFINITE_SPAM: 'definitespam',
        MAYBE_SPAM: 'maybespam',
    }

    # The following should normally be set before comment_check()
    comment_type = models.CharField(max_length=255)
    user_ip = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255)
    referrer = models.CharField(max_length=255)
    user_name = models.CharField(max_length=255)
    user_email = models.CharField(max_length=255)
    user_homepage = models.CharField(max_length=255)
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
            'comment_author_url': self.user_homepage,
            'comment_content': self.comment,
            'comment_date_gmt': self.comment_modified,
            'comment_post_modified_gmt': self.content_modified,
            'blog_charset': 'utf-8',
            'is_test': not settings.AKISMET_REAL_SUBMIT,
        }
        return {key: value for key, value in data.items() if value is not None}

    def _post(self, action):
        log.debug(
            u'Akismet (#{id}) {action}, type: {comment_type}, '
            u'content: {comment}'.format(
                id=self.id, action=action, comment_type=self.comment_type,
                comment=self.comment))
        url = settings.AKISMET_API_URL.format(
            api_key=settings.AKISMET_API_KEY, action=action)
        return requests.post(
            url, data=self._get_data(), headers=self.HEADERS,
            timeout=settings.AKISMET_API_TIMEOUT)

    def _statsd_incr(self):
        metric = self.METRIC_LOOKUP.get(self.result, '')
        statsd.incr(
            'services.akismet.comment_check.%s.%s' % (
                self.comment_type, metric))

    def comment_check(self):
        response = self._post('comment-check')
        try:
            outcome = response.json()
            discard = response.headers.get('X-akismet-pro-tip') == 'discard'
            # Only True or False outcomes are valid.
            if outcome is True or outcome is False:
                self.update(result=(
                    self.HAM if not outcome else
                    self.DEFINITE_SPAM if discard else self.MAYBE_SPAM))
                log.debug('Akismet response %s' % self.get_result_display())
                self._statsd_incr()
                return self.result
        except ValueError:
            # if outcome isn't valid json `response.json` will raise ValueError
            pass
        log.error(
            'Akismet comment-check error: %s' % (
                response.headers.get('X-akismet-debug-help') or response.text))
        self.update(result=self.UNKNOWN)
        self._statsd_incr()
        return self.result

    def _submit(self, spam_or_ham):
        assert spam_or_ham in ('ham', 'spam')
        response = self._post('submit-%s' % spam_or_ham)
        if response.content == 'Thanks for making the web a better place.':
            log.debug('Akismet %s submitted.' % spam_or_ham)
            self.update(reported=True)
            return True
        else:
            log.error('Akismet submit-%s error: %s' % (
                spam_or_ham, response.text))
            return False

    def submit_spam(self):
        # Should be unnecessary, but do some sanity checks.
        assert not self.reported
        assert self.result in [self.HAM]
        return self._submit('spam')

    def submit_ham(self):
        # Should be unnecessary, but do some sanity checks.
        assert not self.reported
        assert self.result in [self.DEFINITE_SPAM, self.MAYBE_SPAM]
        return self._submit('ham')

    @classmethod
    def create_for_rating(cls, rating, user_agent, referrer):
        instance = cls.objects.create(
            rating_instance=rating,
            comment_type='user-review',
            user_ip=rating.ip_address or '',
            user_agent=user_agent or '',
            referrer=referrer or '',
            user_name=rating.user.name or '',
            user_email=rating.user.email,
            user_homepage=rating.user.homepage or '',
            content_link=rating.addon.get_url_path(),
            content_modified=rating.addon.last_updated,
            comment=rating.body,
            comment_modified=rating.modified,
        )
        return instance
