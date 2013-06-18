from datetime import datetime

from django.db import models

from uuidfield.fields import UUIDField

import amo.models
from mkt.constants import comm as const
from translations.fields import TranslatedField, save_signal


class CommunicationThread(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', related_name='threads')
    version = models.ForeignKey('versions.Version', related_name='threads',
                                null=True)

    # Read permissions imply write permissions as well.
    read_permission_public = models.BooleanField()
    read_permission_developer = models.BooleanField()
    read_permission_reviewer = models.BooleanField()
    read_permission_senior_reviewer = models.BooleanField()
    read_permission_mozilla_contact = models.BooleanField()
    read_permission_staff = models.BooleanField()

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


class CommunicationNote(amo.models.ModelBase):
    thread = models.ForeignKey(CommunicationThread, related_name='notes')
    author = models.ForeignKey('users.UserProfile', related_name='comm_notes')
    note_type = models.IntegerField()
    body = TranslatedField()

    class Meta:
        db_table = 'comm_thread_notes'


class CommunicationThreadToken(amo.models.ModelBase):
    thread = models.ForeignKey(CommunicationThread, related_name='token')
    user = models.ForeignKey('users.UserProfile',
                             related_name='comm_thread_tokens')
    uuid = UUIDField(unique=True, auto=True)
    use_count = models.IntegerField(default=0,
        help_text='Stores the number of times the token has been used')

    class Meta:
        db_table = 'comm_thread_tokens'
        unique_together = ('thread', 'user',)

    def is_valid(self):
        # TODO: Confirm the expiration and max use count values.
        timedelta = datetime.now() - self.created
        return (timedelta.days <= const.THREAD_TOKEN_EXPIRY and
                self.use_count < const.MAX_TOKEN_USE_COUNT)


models.signals.pre_save.connect(save_signal, sender=CommunicationNote,
                                dispatch_uid='comm_thread_notes_translations')
