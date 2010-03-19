import datetime

from django.conf import settings
from django.db import models
from django.template import Context, loader

import caching.base
import l10n
from l10n import ugettext as _

from amo.fields import DecimalCharField
from amo.utils import send_mail as amo_send_mail

from .db import StatsDict, StatsDictField, StatsManager


class DownloadCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    # Leave this out of queries if you can.
    sources = StatsDictField(db_column='src', null=True)

    objects = StatsManager('date')

    class Meta:
        db_table = 'download_counts'


class UpdateCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    # Leave these out of queries if you can.
    versions = StatsDictField(db_column='version', null=True)
    statuses = StatsDictField(db_column='status', null=True)
    applications = StatsDictField(db_column='application', null=True)
    oses = StatsDictField(db_column='os', null=True)
    locales = StatsDictField(db_column='locale', null=True)

    objects = StatsManager('date')

    class Meta:
        db_table = 'update_counts'


class ShareCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    service = models.CharField(max_length=255, null=True)
    date = models.DateField()

    objects = StatsManager('date')

    class Meta:
        db_table = 'stats_share_counts'


class ContributionError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class Contribution(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    amount = DecimalCharField(max_digits=9, decimal_places=2,
                              nullify_invalid=True, null=True)
    source = models.CharField(max_length=255, null=True)
    source_locale = models.CharField(max_length=10, null=True)
    annoying = models.BooleanField()
    created = models.DateTimeField(auto_now_add=True)
    uuid = models.CharField(max_length=255, null=True)
    is_suggested = models.BooleanField()
    suggested_amount = DecimalCharField(max_digits=254, decimal_places=2,
                                        nullify_invalid=True, null=True)
    comment = models.CharField(max_length=255)
    transaction_id = models.CharField(max_length=255, null=True)
    post_data = StatsDictField(null=True)

    objects = StatsManager('created')

    class Meta:
        db_table = 'stats_contributions'

    def __unicode__(self):
        return u'%s: %s' % (self.addon.name, self.amount)

    @property
    def date(self):
        try:
            return datetime.date(self.created.year,
                                 self.created.month, self.created.day)
        except AttributeError:
            # created may be None
            return None

    @property
    def contributor(self):
        try:
            return u'%s %s' % (self.post_data['first_name'],
                               self.post_data['last_name'])
        except (TypeError, KeyError):
            # post_data may be None or missing a key
            return None

    @property
    def email(self):
        try:
            return self.post_data['payer_email']
        except (TypeError, KeyError):
            # post_data may be None or missing a key
            return None

    def mail_thankyou(self, request=None):
        """
        Mail a thankyou note for a completed contribution.

        Raises a ``ContributionError`` exception when the contribution
        is not complete or email addresses are not found.
        """

        # Setup l10n before loading addon.
        if self.source_locale:
            lang = self.source_locale
        else:
            lang = self.addon.default_locale
        l10n.activate(lang)

        # Thankyous must be enabled.
        if not self.addon.enable_thankyou:
            # Not an error condition, just return.
            return

        # Contribution must be complete.
        if not self.transaction_id:
            raise ContributionError('Transaction not complete')

        # Send from support_email, developer's email, or default.
        if self.addon.support_email:
            from_email = str(self.addon.support_email)
        else:
            try:
                author = self.addon.listed_authors[0]
                if not author.emailhidden:
                    from_email = author.email
            except IndexError:
                from_email = None
        if not from_email:
            from_email = settings.EMAIL_FROM_DEFAULT

        # We need the contributor's email.
        to_email = self.post_data['payer_email']
        if not to_email:
            raise ContributionError('Empty payer email')

        # Make sure the url uses the right language.
        # Setting a prefixer would be nicer, but that requires a request.
        url_parts = self.addon.meet_the_dev_url().split('/')
        url_parts[1] = lang

        # Buildup the email components.
        t = loader.get_template('stats/contribution-thankyou-email.ltxt')
        c = {
            'thankyou_note': self.addon.thankyou_note,
            'addon_name': self.addon.name,
            'learn_url': settings.SITE_URL + '/'.join(url_parts),
            'domain': settings.DOMAIN,
        }
        body = t.render(Context(c))
        subject = _('Thanks for contributing to {addon_name}').format(
                    addon_name=self.addon.name)

        # Send the email
        if amo_send_mail(subject, body, from_email, [to_email],
                     fail_silently=True):
            # Clear out contributor identifying information.
            del(self.post_data['payer_email'])
            self.save()


class GlobalStat(caching.base.CachingMixin, models.Model):
    name = models.CharField(max_length=255)
    count = models.IntegerField()
    date = models.DateField()

    objects = caching.base.CachingManager()

    class Meta:
        db_table = 'global_stats'
        unique_together = ('name', 'date')
        get_latest_by = 'date'
