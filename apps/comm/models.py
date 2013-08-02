from datetime import datetime

from django.db import models

from uuidfield.fields import UUIDField

import amo.models
from mkt.constants import comm as const
from translations.fields import save_signal


class CommunicationPermissionModel(amo.models.ModelBase):
    # Read permissions imply write permissions as well.
    read_permission_public = models.BooleanField()
    read_permission_developer = models.BooleanField()
    read_permission_reviewer = models.BooleanField()
    read_permission_senior_reviewer = models.BooleanField()
    read_permission_mozilla_contact = models.BooleanField()
    read_permission_staff = models.BooleanField()

    class Meta:
        abstract = True


class CommunicationThread(CommunicationPermissionModel):
    addon = models.ForeignKey('addons.Addon', related_name='threads')
    version = models.ForeignKey('versions.Version', related_name='threads',
                                null=True)

    class Meta:
        db_table = 'comm_threads'


class CommunicationThreadCC(amo.models.ModelBase):
    thread = models.ForeignKey(CommunicationThread,
                               related_name='thread_cc')
    user = models.ForeignKey('users.UserProfile',
        related_name='comm_thread_cc')

    class Meta:
        db_table = 'comm_thread_cc'
        unique_together = ('user', 'thread',)


class CommunicationNote(CommunicationPermissionModel):
    thread = models.ForeignKey(CommunicationThread, related_name='notes')
    author = models.ForeignKey('users.UserProfile', related_name='comm_notes')
    note_type = models.IntegerField()
    body = models.TextField(null=True)
    reply_to = models.ForeignKey('self', related_name='replies', null=True,
                                 blank=True)
    read_by_users = models.ManyToManyField('users.UserProfile',
        through='CommunicationNoteRead')

    class Meta:
        db_table = 'comm_thread_notes'

    def save(self, *args, **kwargs):
        super(CommunicationNote, self).save(*args, **kwargs)
        self.thread.modified = self.created
        self.thread.save()


class CommunicationNoteRead(models.Model):
    user = models.ForeignKey('users.UserProfile')
    note = models.ForeignKey(CommunicationNote)

    class Meta:
        db_table = 'comm_notes_read'


class CommunicationThreadToken(amo.models.ModelBase):
    thread = models.ForeignKey(CommunicationThread, related_name='token')
    user = models.ForeignKey('users.UserProfile',
        related_name='comm_thread_tokens')
    uuid = UUIDField(unique=True, auto=True)
    use_count = models.IntegerField(default=0,
        help_text='Stores the number of times the token has been used')

    class Meta:
        db_table = 'comm_thread_tokens'
        unique_together = ('thread', 'user')

    def is_valid(self):
        # TODO: Confirm the expiration and max use count values.
        timedelta = datetime.now() - self.modified
        return (timedelta.days <= const.THREAD_TOKEN_EXPIRY and
                self.use_count < const.MAX_TOKEN_USE_COUNT)

    def reset_uuid(self):
        # Generate a new UUID.
        self.uuid = UUIDField()._create_uuid().hex


models.signals.pre_save.connect(save_signal, sender=CommunicationNote,
                                dispatch_uid='comm_thread_notes_translations')
