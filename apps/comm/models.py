from datetime import datetime

from django.db import models

from uuidfield.fields import UUIDField

from access import acl
import amo.models
from translations.fields import save_signal

from mkt.constants import comm as const


class CommunicationPermissionModel(amo.models.ModelBase):
    # Read permissions imply write permissions as well.
    read_permission_public = models.BooleanField()
    read_permission_developer = models.BooleanField(default=True)
    read_permission_reviewer = models.BooleanField(default=True)
    read_permission_senior_reviewer = models.BooleanField(default=True)
    read_permission_mozilla_contact = models.BooleanField(default=True)
    read_permission_staff = models.BooleanField(default=True)

    class Meta:
        abstract = True


def check_acls(user, obj, acl_type):
    """Check ACLs."""
    if acl_type == 'moz_contact':
        try:
            return user.email in obj.addon.get_mozilla_contacts()
        except AttributeError:
            return user.email in obj.thread.addon.get_mozilla_contacts()
    if acl_type == 'admin':
        return acl.action_allowed_user(user, 'Admin', '%')
    elif acl_type == 'reviewer':
        return acl.action_allowed_user(user, 'Apps', 'Review')
    elif acl_type == 'senior_reviewer':
        return acl.action_allowed_user(user, 'Apps', 'ReviewEscalated')
    else:
        raise Exception('Invalid ACL lookup.')
    return False


def check_acls_comm_obj(obj, profile):
    """Cross-reference ACLs and Note/Thread permissions."""
    if obj.read_permission_public:
        return True

    if (obj.read_permission_reviewer and
        check_acls(profile, obj, 'reviewer')):
        return True

    if (obj.read_permission_senior_reviewer and
        check_acls(profile, obj, 'senior_reviewer')):
        return True

    if (obj.read_permission_mozilla_contact and
        check_acls(profile, obj, 'moz_contact')):
        return True

    if (obj.read_permission_staff and
        check_acls(profile, obj, 'admin')):
        return True

    return False


def user_has_perm_thread(thread, profile):
    """
    Check if the user has read/write permissions on the given thread.

    Developers of the add-on used in the thread, users in the CC list,
    and users who post to the thread are allowed to access the object.

    Moreover, other object permissions are also checked agaisnt the ACLs
    of the user.
    """
    user_post = CommunicationNote.objects.filter(
        author=profile, thread=thread)
    user_cc = CommunicationThreadCC.objects.filter(
        user=profile, thread=thread)

    if user_post.exists() or user_cc.exists():
        return True

    # User is a developer of the add-on and has the permission to read.
    user_is_author = profile.addons.filter(pk=thread.addon_id)
    if thread.read_permission_developer and user_is_author.exists():
        return True

    return check_acls_comm_obj(thread, profile)


def user_has_perm_note(note, profile):
    """
    Check if the user has read/write permissions on the given note.

    Developers of the add-on used in the note, users in the CC list,
    and users who post to the thread are allowed to access the object.

    Moreover, other object permissions are also checked agaisnt the ACLs
    of the user.
    """
    if note.author.id == profile.id:
        # Let the dude access his own note.
        return True

    # User is a developer of the add-on and has the permission to read.
    user_is_author = profile.addons.filter(pk=note.thread.addon_id)
    if note.read_permission_developer and user_is_author.exists():
        return True

    return check_acls_comm_obj(note, profile)


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


class CommunicationNoteManager(models.Manager):

    def with_perms(self, profile, thread):
        ids = [note.id for note in self.filter(thread=thread) if
               user_has_perm_note(note, profile)]
        return self.filter(id__in=ids)


class CommunicationNote(CommunicationPermissionModel):
    thread = models.ForeignKey(CommunicationThread, related_name='notes')
    author = models.ForeignKey('users.UserProfile', related_name='comm_notes')
    note_type = models.IntegerField()
    body = models.TextField(null=True)
    reply_to = models.ForeignKey('self', related_name='replies', null=True,
                                 blank=True)
    read_by_users = models.ManyToManyField('users.UserProfile',
        through='CommunicationNoteRead')

    objects = CommunicationNoteManager()

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
