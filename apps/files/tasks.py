import hashlib
import urllib

from django.conf import settings

from celeryutils import task
import commonware.log
from tower import ugettext as _

from amo.utils import Message
from addons.models import Addon
from versions.models import Version
from .models import File

task_log = commonware.log.getLogger('z.task')
jp_log = commonware.log.getLogger('z.jp.repack')


@task
def extract_file(viewer, **kw):
    msg = Message('file-viewer:%s' % viewer)
    msg.delete()
    task_log.info('[1@%s] Unzipping %s for file viewer.' % (
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


@task
def migrate_jetpack_versions(ids, **kw):
    # TODO(jbalogh): kill in bug 656997
    for file_ in File.objects.filter(id__in=ids):
        file_.jetpack_version = File.get_jetpack_version(file_.file_path)
        task_log.info('Setting jetpack version to %s for File %s.' %
                      (file_.jetpack_version, file_.id))
        file_.save()


# The version/file creation methods expect a files.FileUpload object.
class FakeUpload(object):

    def __init__(self, path, hash, validation):
        self.path = path
        self.hash = hash
        self.validation = validation


@task
def repackage_jetpack(builder_data, **kw):
    jp_log.info('[1@None] Repackaging jetpack for %s.' % builder_data['id'])
    jp_log.info('; '.join('%s: "%s"' % i for i in builder_data.items()))
    msg = lambda s: ('[{id}]: ' + s).format(**builder_data)

    if builder_data['result'] != 'success':
        jp_log.warning(msg('Build not successful. {result}: {msg}'))
        return

    try:
        addon = Addon.objects.get(id=builder_data['id'])
        old_file = File.objects.get(id=builder_data['file_id'])
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
        with open(filepath, 'rb') as fd:
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
    # TODO: multi-file: have we already created the new version for a different
    # file?
    new_version = Version.from_upload(upload, addon, [old_file.platform])
    new_file = new_version.all_files[0]
    new_file.status = old_file.status
    new_file.save()

    # Sync out the new version.
    addon.update_version()

    # TODO: Email author.
    # TODO: don't send editor notifications about the new file.
    # Return the new file to make testing easier.
    return new_file
