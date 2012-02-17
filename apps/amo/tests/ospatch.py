"""
Nose plugin to restrict access to blacklisted os modules.

Activate by running nosetests --with-ospatch or like this in local settings:

    NOSE_PLUGINS = [
        'amo.tests.ospatch.OSPatch',
    ]
    
    NOSE_ARGS = [
        '--with-ospatch',
    ]

This was originally made to
help identify code that needed to be ported to the Django storage API.

After breaking/fixing the tests, this command was also useful:
egrep '\bos\..*' -R apps/ | grep -v 'os.path' | grep -v 'link.os' | grep -v 'os.environ' | egrep -v 'os\.[A-Z]' | less
"""
import logging
import os
import re
from traceback import extract_stack

from nose.plugins import Plugin

log = logging.getLogger('nose.plugins.ospatch')


class OSRestricted(Exception):
    pass


class OSPatch(Plugin):
    name = 'ospatch'
    score = -1  # load after all other plugins

    def options(self, parser, env=os.environ):
        super(OSPatch, self).options(parser, env=env)
        self.parser = parser

    def configure(self, options, conf):
        super(OSPatch, self).configure(options, conf)
        if not self.enabled:
            return
        self.cmd_options = options
        self.config = conf

    def begin(self):
        log.info('Patching os!')
        import amo
        # e.g. /path/to/zamboni/apps
        amo_path = os.path.abspath(os.path.join(
                                        os.path.dirname(amo.__file__), '..'))
        for name in dir(os):
            if (name not in ('altsep',
                             'curdir',
                             'error',
                             'errno',
                             'extsep',
                             'getenv',
                             'environ',
                             'getcwd',
                             'getpid',
                             'linesep',
                             'lstat',
                             'name',
                             'pardir',
                             'path',
                             'pathsep',
                             'putenv',
                             'sep',
                             'setenv',
                             'strerror',
                             'stat',
                             'sys',
                             'uname',
                             'urandom',)
                and not name.startswith('_')
                and not name[0].isupper()):
                setattr(os, name, _Patch(amo_path, getattr(os, name)))


class _Patch(object):

    def __init__(self, amo_path, orig):
        self.amo_path = amo_path
        self.orig = orig

    def __call__(self, *args, **kw):
        allow_call = False
        is_amo = False
        for filename, lineno, fn, text in extract_stack():
            file_fn = '%s:%s' % (filename, fn)
            if os.path.abspath(filename).startswith(self.amo_path):
                is_amo = True
            if ('settings_test.py' in filename
                # Ignore whitelisted lib usage.
                or 'tempfile.py' in filename
                or 'random.py' in filename
                or '/PIL/' in filename
                # Ignore storage API.
                or 'django/core/files/storage.py:open' in file_fn
                or 'django/core/files/storage.py:exists' in file_fn
                or 'django/core/files/storage.py:listdir' in file_fn
                or 'django/core/files/storage.py:path' in file_fn
                or 'django/core/files/storage.py:size' in file_fn
                or 'django/core/files/storage.py:url' in file_fn
                or 'django/core/files/storage.py:save' in file_fn
                or 'django/core/files/storage.py:delete' in file_fn
                or 'amo/utils.py:path' in file_fn  # storage API
                # These need to operate on local files.
                or 'amo/utils.py:rm_local_tmp_dir' in file_fn
                or 'amo/utils.py:rm_local_tmp_file' in file_fn
                or 'files/utils.py:extract_xpi' in file_fn
                or 'payments/models.py:generate_private_key' in file_fn
                # Ignore some test code.
                or 'tests/test_views_edit.py:setup_image_status' in file_fn
                or 'search/tests/__init__.py:setUp' in file_fn
                or 'amo/tests/__init__.py:xpi_copy_over' in file_fn,
                ):
                allow_call = True
            # print filename, fn
        if not is_amo:
            # Only detect incorrect os usage in AMO.
            allow_call = True
        if allow_call:
            return self.orig(*args, **kw)
        raise OSRestricted('cannot call %s' % self.orig)
