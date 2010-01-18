from django.db import models

import amo
from addons.models import Addon
from users.models import UserProfile
from applications.models import Application
from translations.fields import TranslatedField


class Version(amo.ModelBase):
    addon = models.ForeignKey(Addon)
    license = models.ForeignKey('License')
    releasenotes = TranslatedField()
    approvalnotes = models.TextField()
    version = models.CharField(max_length=255, default=0)

    class Meta(amo.ModelBase.Meta):
        db_table = 'versions'


class License(amo.ModelBase):
    rating = models.SmallIntegerField(default=-1)
    text = TranslatedField()

    class Meta(amo.ModelBase.Meta):
        db_table = 'licenses'


class VersionComment(amo.ModelBase):
    """Editor comments for version discussion threads."""
    version = models.ForeignKey(Version)
    user = models.ForeignKey(UserProfile)
    reply_to = models.ForeignKey(Version, related_name="reply_to", null=True)
    subject = models.CharField(max_length=1000)
    comment = models.TextField()

    class Meta(amo.ModelBase.Meta):
        db_table = 'versioncomments'


class VersionSummary(amo.ModelBase):
    addon = models.ForeignKey(Addon)
    version = models.ForeignKey(Version)
    application = models.ForeignKey(Application)
    min = models.IntegerField(null=True)
    max = models.IntegerField(null=True)

    class Meta(amo.ModelBase.Meta):
        db_table = 'versions_summary'
