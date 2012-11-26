import json

from django.core.management.base import BaseCommand
from django.db import connection, transaction

import amo
from addons.models import Webapp
from files.models import File
from versions.models import Version


class Command(BaseCommand):
    help = 'Collapse versions for hosted apps'

    def handle(self, *args, **kwargs):
        do_collapsing()


def do_collapsing():
    cursor = connection.cursor()
    vkey = unicode(Version._meta)
    fkey = 'files'

    for app in (Webapp.uncached.filter(type=amo.ADDON_WEBAPP,
                                       disabled_by_user=False,
                                       is_packaged=False)
                               .exclude(status=amo.STATUS_DELETED)
                               .no_transforms()):

        with transaction.commit_on_success():

            print 'Updating app [%s]' % app.id

            try:
                version = (Version.objects.filter(addon=app)
                                          .no_transforms().latest())
            except Version.DoesNotExist:
                print 'App [%s] has no version? FIXME!' % app.id
                continue

            try:
                file_ = File.objects.filter(version=version).latest()
            except File.DoesNotExist:
                file_ = None

            old_versions = (app.versions.exclude(pk=version.id)
                                        .no_transforms()
                                        .order_by('-created'))
            if not old_versions:
                print 'No older versions found.'
                continue

            # Set the current_version to the one we're collapsing to. This
            # avoids integrity errors as we delete versions below.
            if app._current_version.id != version.id:
                cursor.execute('''
                    UPDATE addons SET current_version=%s
                    WHERE id=%s''', (version.id, app.id,))
                app._current_version = version
                print 'Set current_version for app [%s] to [%s]' % (
                    app.id, version.id)

            for old_version in old_versions:

                # Hosted app reviews' version column is always NULL.
                # `versioncomments` has no data for apps.
                # `applications_versions` has no data for apps.

                # VersionLogs and ActivityLogs
                cursor.execute('''
                    SELECT t1.id, t1.version_id, t2.id, t2.arguments, t2.details
                    FROM log_activity_version_mkt AS t1
                    JOIN log_activity_mkt AS t2
                        ON t1.activity_log_id=t2.id
                    WHERE t1.version_id=%s''', (old_version.id,))
                for row in cursor.fetchall():
                    (lav_id, lav_version_id,
                     la_id, la_arguments, la_details) = row

                    arguments = details = None
                    if la_arguments:
                        arguments = json.loads(la_arguments)
                    if la_details:
                        details = json.loads(la_details)

                    do_arguments_save = do_details_save = False

                    # arguments looks like:
                    # [{"webapps.webapp": 8}, {"versions.version": 8}]
                    for _a in arguments:
                        if vkey in _a:
                            _a[vkey] = version.id
                            do_arguments_save = True

                    # details looks like:
                    # {"files": [35], "reviewtype": "pending", "comments": "yo"}
                    if file_ and details and fkey in details:
                        details[fkey] = [file_.id]
                        do_details_save = True

                    if do_arguments_save or do_details_save:
                        new_a = json.dumps(arguments) if arguments else ''
                        new_d = json.dumps(details) if details else ''
                        cursor.execute('''
                            UPDATE log_activity_mkt
                            SET arguments=%s, details=%s
                            WHERE id=%s''', (new_a, new_d, la_id))

                        if do_arguments_save:
                            print 'Activity log [%s] arguments updated: %s' % (
                                la_id, new_a)
                        if do_details_save:
                            print 'Activity log [%s] details updated: %s' % (
                                la_id, new_d)

                    cursor.execute('''
                        UPDATE log_activity_version_mkt
                        SET version_id=%s
                        WHERE id=%s''', (version.id, lav_id))

                    print 'Version log [%s] version id updated: %s => %s' % (
                        lav_id, old_version.id, version.id)

                # There are stale activity logs without the _mkt suffix that we
                # need to deal with to avoid integrity errors when we delete
                # the version.
                cursor.execute('''
                    SELECT activity_log_id FROM log_activity_version
                    WHERE version_id=%s''', (old_version.id,))
                for row in cursor.fetchall():
                    cursor.execute('''
                        DELETE FROM log_activity_app
                        WHERE activity_log_id=%s''', (row[0],))
                    cursor.execute('''
                        DELETE FROM log_activity_comment
                        WHERE activity_log_id=%s''', (row[0],))
                    cursor.execute('''
                        DELETE FROM log_activity_user
                        WHERE activity_log_id=%s''', (row[0],))
                    cursor.execute('''
                        DELETE FROM log_activity_version
                        WHERE activity_log_id=%s''', (row[0],))
                    cursor.execute(
                        'DELETE FROM log_activity WHERE id=%s', (row[0],))

                # Copy over important fields if not set on current version.
                if not version.releasenotes and old_version.releasenotes:
                    version.releasenotes = old_version.releasenotes
                    print 'Copied releasenotes (%s) from old_version [%s].' % (
                        version.releasenotes, old_version.id)

                if not version.approvalnotes and old_version.approvalnotes:
                    version.approvalnotes = old_version.approvalnotes
                    print 'Copied approvalnotes (%s) from old_version [%s].' % (
                        version.approvalnotes, old_version.id)

                if not version.reviewed and old_version.reviewed:
                    version.reviewed = old_version.reviewed
                    print 'Copied reviewed date (%s) from old version [%s].' % (
                        version.reviewed, old_version.id)

                if (not version.has_editor_comment and
                    old_version.has_editor_comment):
                    version.has_editor_comment = old_version.has_editor_comment
                    print 'Copied editor_comment flag from old version [%s].' % (
                        old_version.id,)

                if (not version.has_info_request and
                    old_version.has_info_request):
                    version.has_info_request = old_version.has_info_request
                    print 'Copied info_request flag from old version [%s].' % (
                        old_version.id,)

                # Always take the oldest created stamp since we want to keep
                # the first version's values.
                if old_version.created < version.created:
                    version.created = old_version.created

                # Delete this version's files and on-disk files.
                cursor.execute('''
                    DELETE FROM files
                    WHERE version_id=%s''', (old_version.id,))
                print 'Deleted files records attached to version [%s]' % (
                    old_version.id,)

                old_files = File.objects.filter(version_id=old_version.id)
                for f in old_files:
                    print 'Please remove file from file system: %s' % f.file_path
                    File.objects.invalidate(f)

                # Delete the version itself.
                cursor.execute('''
                    DELETE FROM versions
                    WHERE id=%s''', (old_version.id,))
                Version.objects.invalidate(old_version)
                print 'Deleted version [%s]' % old_version.id

            # Save version to update any fields that were copied above.
            version.save()

            # Copy the file reviewed date if not set.
            if (version.reviewed and not file_.reviewed and
                file_.reviewed != version.reviewed):
                file_.update(reviewed=version.reviewed)

            # Call app.save to invalidate and re-index, etc.
            if file_:
                app.save()
