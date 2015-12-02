import logging
import os
import shutil

from django.conf import settings

import spidermonkey
from cache_nuggets.lib import Message
from tower import ugettext as _

import amo
from addons.models import Addon, AddonUser
from amo.celery import task
from files.utils import repack, update_version_number
from lib.crypto.packaged import sign_file
from versions.compare import version_int


log = logging.getLogger('z.task')


@task
def extract_file(viewer, **kw):
    # This message is for end users so they'll see a nice error.
    msg = Message('file-viewer:%s' % viewer)
    msg.delete()
    # This flag is so that we can signal when the extraction is completed.
    flag = Message(viewer._extraction_cache_key())
    log.debug('[1@%s] Unzipping %s for file viewer.' % (
              extract_file.rate_limit, viewer))

    try:
        flag.save('extracting')  # Set the flag to a truthy value.
        viewer.extract()
    except Exception, err:
        if settings.DEBUG:
            msg.save(_('There was an error accessing file %s. %s.') %
                     (viewer, err))
        else:
            msg.save(_('There was an error accessing file %s.') % viewer)
        log.error('[1@%s] Error unzipping: %s' %
                  (extract_file.rate_limit, err))
    finally:
        # Always delete the flag so the file never gets into a bad state.
        flag.delete()


def fix_let_scope_bustage(*files):
    """Needed for bug 1224444: rewrite all the top level `let` to `var`.

    Usage:
    >>> fix_let_scope_bustage(file1, file2, file3, ...)
    ('', '')  # First one is stdout, second is stderr.
    """
    fixage_script = os.path.join('scripts', 'rewrite.js')
    # We need to force the version to 180, because in 185 there were some
    # breaking changes: using `function` for generators was deprecated, but a
    # lot of the current add-ons are using that.
    process = spidermonkey.Spidermonkey(code='version(180)',
                                        script_file=fixage_script,
                                        script_args=files)
    return process.communicate()


def fix_let_scope_bustage_in_xpi(xpi_path):
    """Rewrite all the top level `let` to `var` in an XPI."""
    files_to_fix = []
    with repack(xpi_path) as folder:
        for root, dirs, files in os.walk(folder):
            for file_ in files:
                if file_.endswith('.js'):
                    # We only want to fix javascript files.
                    files_to_fix.append(os.path.join(root, file_))
        fix_let_scope_bustage(*files_to_fix)


MAIL_SUBJECT = u'Mozilla Add-ons: {addon} has been automatically fixed on AMO'
MAIL_MESSAGE = u"""
Your add-on, {addon}, has been automatically fixed for future versions of
Firefox (see
https://blog.mozilla.org/addons/2015/10/14/breaking-changes-let-const-firefox-nightly-44/).
The fixing process involved repackaging the add-on files and adding the string
'.1-let-fixed' to their versions numbers. We only fixed the files for the
last uploaded version.
We recommend that you give them a try to make sure they don't have any
unexpected problems: {addon_url}

Future uploads will not be repackaged, so please make sure to integrate these
changes into your source code. The blog post linked above explains in detail
what changed and how it affects your code.

If you have any questions or comments on this, please reply to this email or
join #addons on irc.mozilla.org.

You're receiving this email because you have an add-on hosted on
https://addons.mozilla.org
"""


@task
def fix_let_scope_bustage_in_addons(addon_ids):
    """Used to fix the "let scope bustage" (bug 1224686) in the last version of
    the provided add-ons.

    This is used in the 'fix_let_scope_bustage' management commands.

    It also bumps the version number of the file and the Version, so the
    Firefox extension update mecanism picks this new fixed version and installs
    it.
    """
    log.info(u'[{0}] Fixing addons.'.format(len(addon_ids)))

    addons_emailed = []
    for addon in Addon.objects.filter(id__in=addon_ids):
        # We only care about the latest added version for each add-on.
        version = addon.versions.first()
        log.info(u'Fixing addon {0}, version {1}'.format(addon, version))

        bumped_version_number = u'{0}.1-let-fixed'.format(version.version)
        for file_obj in version.files.all():
            if not os.path.isfile(file_obj.file_path):
                log.info(u'File {0} does not exist, skip'.format(file_obj.pk))
                continue
            # Save the original file, before bumping the version.
            backup_path = u'{0}.backup_let_fix'.format(file_obj.file_path)
            shutil.copy(file_obj.file_path, backup_path)
            try:
                # Apply the fix itself.
                fix_let_scope_bustage_in_xpi(file_obj.file_path)
            except:
                log.error(u'Failed fixing file {0}'.format(file_obj.pk),
                          exc_info=True)
                # Revert the fix by restoring the backup.
                shutil.move(backup_path, file_obj.file_path)
                continue  # We move to the next file.
            # Need to bump the version (modify install.rdf or package.json)
            # before the file is signed.
            update_version_number(file_obj, bumped_version_number)
            if file_obj.is_signed:  # Only sign if it was already signed.
                if file_obj.status == amo.STATUS_PUBLIC:
                    server = settings.SIGNING_SERVER
                else:
                    server = settings.PRELIMINARY_SIGNING_SERVER
                sign_file(file_obj, server)
            # Now update the Version model.
            version.update(version=bumped_version_number,
                           version_int=version_int(bumped_version_number))
            addon = version.addon
            if addon.pk not in addons_emailed:
                # Send a mail to the owners/devs warning them we've
                # automatically fixed their addon.
                qs = (AddonUser.objects
                      .filter(role=amo.AUTHOR_ROLE_OWNER, addon=addon)
                      .exclude(user__email__isnull=True))
                emails = qs.values_list('user__email', flat=True)
                subject = MAIL_SUBJECT.format(addon=addon.name)
                message = MAIL_MESSAGE.format(
                    addon=addon.name,
                    addon_url=amo.helpers.absolutify(
                        addon.get_dev_url(action='versions')))
                amo.utils.send_mail(
                    subject, message, recipient_list=emails,
                    fail_silently=True,
                    headers={'Reply-To': 'amo-editors@mozilla.org'})
                addons_emailed.append(addon.pk)
