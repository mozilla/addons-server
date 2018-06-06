import logging
import random
import collections
import os
import string
import re
import tempfile
import uuid
from contextlib import contextmanager
from shutil import make_archive, rmtree
from zipfile import ZipFile

import lxml

from fxa.constants import ENVIRONMENT_URLS
from fxa.core import Client
from fxa.tests.utils import TestEmailAccount

NAME_REGEX = re.compile('THIS_IS_THE_NAME')

root_path = os.path.dirname(__file__)
data_dir = os.path.join(root_path, 'fixtures')
xpis = [os.path.join(data_dir, xpi) for xpi in os.listdir(data_dir)]
log = logging.getLogger(__name__)


def get_random():
    return str(uuid.uuid4())


def submit_url(step):
    return '/en-US/developers/addon/submit/{step}/'.format(step=step)


def get_xpi():
    return uniqueify_xpi(random.choice(xpis))


@contextmanager
def uniqueify_xpi(path):
    output_dir = tempfile.mkdtemp()
    try:
        data_dir = os.path.join(output_dir, 'xpi')
        output_path = os.path.join(output_dir, 'addon')
        xpi_name = os.path.basename(path)
        xpi_path = os.path.join(output_dir, xpi_name)

        with ZipFile(path) as original:
            original.extractall(data_dir)

        with open(os.path.join(data_dir, 'manifest.json')) as f:
            manifest_json = f.read()

        manifest_json = NAME_REGEX.sub(get_random(), manifest_json)

        with open(os.path.join(data_dir, 'manifest.json'), 'w') as f:
            f.write(manifest_json)

        archive_path = make_archive(output_path, 'zip', data_dir)
        os.rename(archive_path, xpi_path)
        with open(xpi_path) as f:
            yield f
    finally:
        rmtree(output_dir)


class EventMarker(object):
    """
    Simple event marker that logs on every call.
    """
    def __init__(self, name):
        self.name = name

    def _generate_log_message(self):
        log.info('locust event: {}'.format(self.name))

    def __call__(self, *args, **kwargs):
        self._generate_log_message()


def install_event_markers():
    # "import locust" within this scope so that this module is importable by
    # code running in environments which do not have locust installed.
    import locust

    # The locust logging format is not necessarily stable, so we use the event
    # hooks API to implement our own "stable" logging for later programmatic
    # reference.

    # The events are:

    # * locust_start_hatching
    # * master_start_hatching
    # * quitting
    # * hatch_complete

    # install simple event markers
    locust.events.locust_start_hatching += EventMarker('locust_start_hatching')
    locust.events.master_start_hatching += EventMarker('master_start_hatching')
    locust.events.quitting += EventMarker('quitting')
    locust.events.hatch_complete += EventMarker('hatch_complete')


def get_fxa_client():
    fxa_env = os.getenv('FXA_ENV', 'stable')
    return Client(ENVIRONMENT_URLS[fxa_env]['authentication'])


def get_fxa_account():
    fxa_client = get_fxa_client()

    account = TestEmailAccount()
    password = ''.join([random.choice(string.ascii_letters) for i in range(8)])
    FxAccount = collections.namedtuple('FxAccount', 'email password')
    fxa_account = FxAccount(email=account.email, password=password)
    session = fxa_client.create_account(fxa_account.email,
                                        fxa_account.password)
    account.fetch()
    message = account.wait_for_email(lambda m: 'x-verify-code' in m['headers'])
    session.verify_email_code(message['headers']['x-verify-code'])
    return fxa_account, account


def destroy_fxa_account(fxa_account, email_account):
    email_account.clear()
    get_fxa_client().destroy_account(fxa_account.email, fxa_account.password)


def get_the_only_form_without_id(response_content):
    """
    Gets the only form on the page that doesn't have an ID.

    A lot of pages (login, registration) have a single form without an ID.
    This is the one we want. The other forms on the page have IDs so we
    can ignore them. I'm sure this will break one day.
    """
    html = lxml.html.fromstring(response_content)
    target_form = None
    for form in html.forms:
        if not form.attrib.get('id'):
            target_form = form
    if target_form is None:
        raise ValueError(
            'Could not find only one form without an ID; found: {}'
            .format(html.forms))
    return target_form
