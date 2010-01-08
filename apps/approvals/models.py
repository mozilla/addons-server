from django.db import models

import amo


class Approval(amo.ModelBase):

    reviewtype = models.CharField(max_length=10, default='pending')
    action = models.IntegerField(default=0)
    os = models.CharField(max_length=255, default='')
    applications = models.CharField(max_length=255, default='')
    comments = models.TextField(null=True)

    addon = models.ForeignKey('addons.Addon')
    user = models.ForeignKey('users.UserProfile')
    #file = models.ForeignKey('files.File')
    reply_to = models.ForeignKey('self', null=True, db_column='reply_to')

    class Meta(amo.ModelBase.Meta):
        db_table = 'approvals'
