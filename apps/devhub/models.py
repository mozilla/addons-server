from datetime import datetime

from django.db import models

import amo.models
from translations.fields import TranslatedField


LOG = {
    'Create Add-on': 1,
    'Edit Properties': 2,
    'Edit Descriptions': 3,
    'Edit Categories': 4,
    'Add User with Role': 5,
    'Remove User with Role': 6,
    'Edit Contributions': 7,

    'Set Inactive': 8,
    'Unset Inactive': 9,
    'Set Public Stats': 10,
    'Unset Public Stats': 11,
    'Change Status': 12,

    'Add Preview': 13,
    'Edit Preview': 14,
    'Delete Preview': 15,

    'Add Version': 16,
    'Edit Version': 17,
    'Delete Version': 18,
    'Add File to Version': 19,
    'Delete File from Version': 20,

    'Approve Version': 21,
    'Retain Version': 22,
    'Escalate Version': 23,
    'Request Version': 24,

    'Add Tag': 25,
    'Remove Tag': 26,

    'Add to Collection': 27,
    'Remove from Collection': 28,

    'Add Review': 29,

    'Add Recommended Category': 31,
    'Remove Recommended Category': 32,

    'Add Recommended': 33,
    'Remove Recommended': 34,

    'Add Appversion': 35,

    'Custom Text': 98,
    'Custom HTML': 99,
}


class HubPromo(amo.models.ModelBase):
    VISIBILITY_CHOICES = (
        (0, 'Nobody'),
        (1, 'Visitors'),
        (2, 'Developers'),
        (3, 'Visitors and Developers'),
    )

    heading = TranslatedField()
    body = TranslatedField()
    visibility = models.SmallIntegerField(choices=VISIBILITY_CHOICES)

    class Meta:
        db_table = 'hubpromos'

    def __unicode__(self):
        return unicode(self.heading)


class HubEvent(amo.models.ModelBase):
    name = models.CharField(max_length=255, default='')
    url = models.URLField(max_length=255, default='')
    location = models.CharField(max_length=255, default='')
    date = models.DateField(default=datetime.now)

    class Meta:
        db_table = 'hubevents'

    def __unicode__(self):
        return self.name


class AddonLog(models.Model):
    TYPES = [(value, key) for key, value in LOG.items()]

    addon = models.ForeignKey('addons.Addon', null=True, blank=True)
    user = models.ForeignKey('users.UserProfile', null=True)
    type = models.SmallIntegerField(choices=TYPES)
    object1_id = models.IntegerField(null=True, blank=True)
    object2_id = models.IntegerField(null=True, blank=True)
    name1 = models.CharField(max_length=255, default='', blank=True)
    name2 = models.CharField(max_length=255, default='', blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'addonlogs'
