from datetime import datetime
import hashlib
import logging
import os
import urllib
import urllib2
import urlparse
import uuid

import django.core.mail
from django.conf import settings
from django.db import transaction
from django.core.files.storage import default_storage as storage

import jingo
from celeryutils import task
from tower import ugettext as _

import amo
from amo.decorators import write
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from amo.utils import Message, get_email_backend
from addons.models import Addon
from versions.compare import version_int as vint
from versions.models import Version, ApplicationsVersions
from .models import File
from .utils import JetpackUpgrader, parse_addon

task_log = logging.getLogger('z.task')
jp_log = logging.getLogger('z.jp.repack')


@task
def extract_file(viewer, **kw):
    # This message is for end users so they'll see a nice error.
    msg = Message('file-viewer:%s' % viewer)
    msg.delete()
    # This flag is so that we can signal when the extraction is completed.
    flag = Message(viewer._extraction_cache_key())
    task_log.debug('[1@%s] Unzipping %s for file viewer.' % (
                  extract_file.rate_limit, viewer))

    try:
        viewer.extract()
    except Exception, err:
        if settings.DEBUG:
            msg.save(_('There was an error accessing file %s. %s.') %
                     (viewer, err))
        else:
            msg.save(_('There was an error accessing file %s.') % viewer)
        task_log.error('[1@%s] Error unzipping: %s' %
                       (extract_file.rate_limit, err))

    flag.delete()


# The version/file creation methods expect a files.FileUpload object.
class FakeUpload(object):

    def __init__(self, path, hash, validation):
        self.path = path
        self.name = os.path.basename(path)
        self.hash = hash
        self.validation = validation


class RedisLogHandler(logging.Handler):
    """Logging handler that sends jetpack messages to redis."""

    def __init__(self, logger, upgrader, file_data, level=logging.WARNING):
        self.logger = logger
        self.upgrader = upgrader
        self.file_data = file_data
        logging.Handler.__init__(self, level)

    def emit(self, record):
        self.file_data['status'] = 'failed'
        self.file_data['msg'] = record.msg
        if 'file' in self.file_data:
            self.upgrader.file(self.file_data['file'], self.file_data)
        self.logger.removeHandler(self)


@task
@write
@transaction.commit_on_success
def repackage_jetpack(builder_data, **kw):
    repack_data = dict(urlparse.parse_qsl(builder_data['request']))
    jp_log.info('[1@None] Repackaging jetpack for %s.'
                % repack_data['file_id'])
    jp_log.info('; '.join('%s: "%s"' % i for i in builder_data.items()))
    all_keys = builder_data.copy()
    all_keys.update(repack_data)
    msg = lambda s: ('[{file_id}]: ' + s).format(**all_keys)
    upgrader = JetpackUpgrader()
    file_data = upgrader.file(repack_data['file_id'])

    redis_logger = RedisLogHandler(jp_log, upgrader, file_data)
    jp_log.addHandler(redis_logger)
    if file_data.get('uuid') != repack_data['uuid']:
        _msg = ('Aborting repack. AMO<=>Builder tracking number mismatch '
                '(%s) (%s)' % (file_data.get('uuid'), repack_data['uuid']))
        return jp_log.warning(msg(_msg))

    if builder_data['result'] != 'success':
        return jp_log.warning(msg('Build not successful. {result}: {msg}'))

    try:
        addon = Addon.objects.get(id=repack_data['addon'])
        old_file = File.objects.get(id=repack_data['file_id'])
        old_version = old_file.version
    except Exception:
        jp_log.error(msg('Could not find addon or file.'), exc_info=True)
        raise

    # Fetch the file from builder.amo.
    try:
        filepath, headers = urllib.urlretrieve(builder_data['location'])
    except Exception:
        jp_log.error(msg('Could not retrieve {location}.'), exc_info=True)
        raise

    # Figure out the SHA256 hash of the file.
    try:
        hash_ = hashlib.sha256()
        with storage.open(filepath, 'rb') as fd:
            while True:
                chunk = fd.read(8192)
                if not chunk:
                    break
                hash_.update(chunk)
    except Exception:
        jp_log.error(msg('Error hashing file.'), exc_info=True)
        raise

    upload = FakeUpload(path=filepath, hash='sha256:%s' % hash_.hexdigest(),
                        validation=None)
    try:
        version = parse_addon(upload, addon)['version']
        if addon.versions.filter(version=version).exists():
            jp_log.warning('Duplicate version [%s] for %r detected. Bailing.'
                           % (version, addon))
            return
    except Exception:
        pass

    # TODO: multi-file: have we already created the new version for a different
    # file?
    try:
        new_version = Version.from_upload(upload, addon, [old_file.platform],
                                          send_signal=False)
    except Exception:
        jp_log.error(msg('Error creating new version.'))
        raise

    try:
        # Sync the compatible apps of the new version with data from the old
        # version if the repack didn't specify compat info.
        for app in old_version.apps.values():
            sync_app = amo.APP_IDS[app['application_id']]
            new_compat = new_version.compatible_apps
            if sync_app not in new_compat:
                app.update(version_id=new_version.id, id=None)
                ApplicationsVersions.objects.create(**app)
            else:
                new_compat[sync_app].min_id = app['min_id']
                new_compat[sync_app].max_id = app['max_id']
                new_compat[sync_app].save()
    except Exception:
        jp_log.error(msg('Error syncing compat info. [%s] => [%s]' %
                         (old_version.id, new_version.id)), exc_info=True)
        pass  # Skip this for now, we can fix up later.

    try:
        # Sync the status of the new file.
        new_file = new_version.files.using('default')[0]
        new_file.status = old_file.status
        new_file.save()
        if (addon.status in amo.MIRROR_STATUSES
            and new_file.status in amo.MIRROR_STATUSES):
            new_file.copy_to_mirror()
    except Exception:
        jp_log.error(msg('Error syncing old file status.'), exc_info=True)
        raise

    # Sync out the new version.
    addon.update_version()
    upgrader.finish(repack_data['file_id'])
    jp_log.info('Repacked %r from %r for %r.' %
                (new_version, old_version, addon))
    jp_log.removeHandler(redis_logger)

    try:
        send_upgrade_email(addon, new_version, file_data['version'])
    except Exception:
        jp_log.error(msg('Could not send success email.'), exc_info=True)
        raise

    # Return the new file to make testing easier.
    return new_file


def send_upgrade_email(addon, new_version, sdk_version):
    cxn = get_email_backend()
    subject = u'%s updated to SDK version %s' % (addon.name, sdk_version)
    from_ = settings.DEFAULT_FROM_EMAIL
    to = set(addon.authors.values_list('email', flat=True))
    t = jingo.env.get_template('files/jetpack_upgraded.txt')
    msg = t.render(addon=addon, new_version=new_version,
                   sdk_version=sdk_version)
    django.core.mail.send_mail(subject, msg, from_, to, connection=cxn)


@task
def start_upgrade(file_ids, sdk_version=None, priority='low', **kw):
    upgrader = JetpackUpgrader()
    minver, maxver = upgrader.jetpack_versions()
    files = File.objects.filter(id__in=file_ids).select_related('version')
    now = datetime.now()
    filedata = {}
    for file_ in files:
        if not (file_.jetpack_version and
                vint(minver) <= vint(file_.jetpack_version) < vint(maxver)):
            continue

        jp_log.info('Sending %s to builder for jetpack version %s.'
                    % (file_.id, maxver))
        # Data stored locally so we can figure out job details and if it should
        # be cancelled.
        data = {'file': file_.id,
                'version': maxver,
                'time': now,
                'uuid': uuid.uuid4().hex,
                'status': 'Sent to builder',
                'owner': 'bulk'}

        # Data POSTed to the builder.
        post = {'addon': file_.version.addon_id,
                'file_id': file_.id,
                'priority': priority,
                'secret': settings.BUILDER_SECRET_KEY,
                'uuid': data['uuid'],
                'pingback': absolutify(reverse('amo.builder-pingback'))}
        if file_.builder_version:
            post['package_key'] = file_.builder_version
        else:
            # Older jetpacks might not have builderVersion in their harness.
            post['location'] = file_.get_url_path('builder')
        if sdk_version:
            post['sdk_version'] = sdk_version
        try:
            jp_log.info(urllib.urlencode(post))
            response = urllib2.urlopen(settings.BUILDER_UPGRADE_URL,
                                       urllib.urlencode(post))
            jp_log.info('Response from builder for %s: [%s] %s' %
                         (file_.id, response.code, response.read()))
        except Exception:
            jp_log.error('Could not talk to builder for %s.' % file_.id,
                         exc_info=True)
        filedata[file_.id] = data
    upgrader.files(filedata)


@task
def watermark_task(file, user):
    task_log.info('Starting watermarking of: %s' % file.pk)
    file.watermark(user)
