import collections
import datetime
import hashlib
import inspect
import os.path
import tempfile
from unittest import mock

from django.conf import settings
from django.test import RequestFactory
from django.test.utils import override_settings
from django.utils.functional import cached_property
from django.utils.http import quote_etag

import pytest
import time_machine
from babel import Locale
from google.api_core.exceptions import PreconditionFailed

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.utils import (
    HttpResponseXSendFile,
    attach_trans_dict,
    backup_storage_blob,
    backup_storage_enabled,
    copy_file_to_backup_storage,
    create_signed_url_for_file_backup,
    download_file_contents_from_backup_storage,
    extract_colors_from_image,
    generate_lowercase_homoglyphs_variants_for_string,
    get_locale_from_lang,
    id_to_path,
    is_safe_url,
    normalize_string_for_name_checks,
    pngcrush_image,
    utc_millesecs_from_epoch,
    walkfiles,
)
from olympia.constants.abuse import REPORTED_MEDIA_BACKUP_EXPIRATION_DAYS
from olympia.core.languages import LANGUAGES_NOT_IN_BABEL


pytestmark = pytest.mark.django_db

IMAGE_FILESIZE_MAX = 200 * 1024


class TestAttachTransDict(TestCase):
    """
    Tests for attach_trans_dict. For convenience, we re-use Addon model instead
    of mocking one from scratch and we rely on internal Translation unicode
    implementation, because mocking django models and fields is just painful.
    """

    def test_basic(self):
        addon = addon_factory(
            name='Name',
            description='Description <script>alert(42)</script>!',
            eula='',
            summary='Summary',
            homepage='http://home.pa.ge',
            developer_comments='Developer Comments',
            support_email='sup@example.com',
            support_url='http://su.pport.url',
        )
        addon.save()

        # Quick sanity checks: is description properly escaped? The underlying
        # implementation should leave localized_string un-escaped but never use
        # it for __str__. We depend on this behaviour later in the test.
        assert '<script>' in addon.description.localized_string
        assert '<script>' not in addon.description.localized_string_clean
        assert '<script>' not in str(addon.description)

        # Attach trans dict.
        attach_trans_dict(Addon, [addon])
        assert isinstance(addon.translations, collections.defaultdict)
        translations = dict(addon.translations)

        # addon.translations is a defaultdict.
        assert addon.translations['whatever'] == []

        # No-translated fields should be absent.
        assert addon.privacy_policy_id is None
        assert None not in translations

        # Build expected translations dict.
        expected_translations = {
            addon.eula_id: [('en-us', str(addon.eula))],
            addon.description_id: [('en-us', str(addon.description))],
            addon.developer_comments_id: [('en-us', str(addon.developer_comments))],
            addon.summary_id: [('en-us', str(addon.summary))],
            addon.homepage_id: [('en-us', str(addon.homepage))],
            addon.name_id: [('en-us', str(addon.name))],
            addon.support_email_id: [('en-us', str(addon.support_email))],
            addon.support_url_id: [('en-us', str(addon.support_url))],
        }
        assert translations == expected_translations

    def test_no_objects(self):
        # Calling attach_trans_dict on an empty list/queryset shouldn't do anything.
        attach_trans_dict(Addon, [])
        attach_trans_dict(Addon, Addon.objects.none())

    def test_deferred_field(self):
        addon = addon_factory(
            name='Name',
            description='Description <script>alert(42)</script>!',
            eula='',
            summary='Summary',
            homepage='http://home.pa.ge',
            developer_comments='Developer Comments',
            support_email='sup@example.com',
            support_url='http://su.pport.url',
        )
        addon.save()
        description_id = addon.description_id

        addons = Addon.objects.defer('description').all()
        attach_trans_dict(Addon, addons)
        addon = addons[0]
        assert isinstance(addon.translations, collections.defaultdict)
        translations = dict(addon.translations)
        assert translations[addon.name_id]
        assert description_id not in translations

    def test_defer_all_fields(self):
        addon = addon_factory(
            name='Name',
            description='Description <script>alert(42)</script>!',
            eula='',
            summary='Summary',
            homepage='http://home.pa.ge',
            developer_comments='Developer Comments',
            support_email='sup@example.com',
            support_url='http://su.pport.url',
        )
        addon.save()

        addons = Addon.objects.only('id').all()
        attach_trans_dict(Addon, addons)
        addon = addons[0]
        assert isinstance(addon.translations, collections.defaultdict)
        translations = dict(addon.translations)
        assert list(translations.values()) == []

    def test_multiple_objects_with_multiple_translations(self):
        addon = addon_factory()
        addon.description = {'fr': 'French Description', 'en-us': 'English Description'}
        addon.save()
        addon2 = addon_factory(description='English 2 Description')
        addon2.name = {
            'fr': 'French 2 Name',
            'en-us': 'English 2 Name',
            'es-es': 'Spanish 2 Name',
        }
        addon2.save()
        attach_trans_dict(Addon, [addon, addon2, None])
        assert set(addon.translations[addon.description_id]) == (
            {('en-us', 'English Description'), ('fr', 'French Description')}
        )
        assert set(addon2.translations[addon2.name_id]) == (
            {
                ('en-us', 'English 2 Name'),
                ('es-es', 'Spanish 2 Name'),
                ('fr', 'French 2 Name'),
            }
        )

    def test_specific_fields_only(self):
        addon = addon_factory()
        addon.description = {'fr': 'French Description', 'en-us': 'English Description'}
        addon.name = {'de': 'German Næme', 'en-us': 'English Name'}
        addon.save()
        addon2 = addon_factory(
            description='English 2 Description', homepage='https://example.com'
        )
        addon2.name = {
            'fr': 'French 2 Name',
            'en-us': 'English 2 Name',
            'es-es': 'Spanish 2 Name',
        }
        addon2.save()
        attach_trans_dict(
            Addon,
            [addon, addon2],
            field_names=['name', 'homepage'],
        )
        assert set(addon.translations.keys()) == {addon.name_id}
        assert set(addon.translations[addon.name_id]) == {
            ('en-us', 'English Name'),
            ('de', 'German Næme'),
        }
        assert set(addon2.translations.keys()) == {addon2.name_id, addon2.homepage_id}
        assert set(addon2.translations[addon2.name_id]) == {
            ('es-es', 'Spanish 2 Name'),
            ('en-us', 'English 2 Name'),
            ('fr', 'French 2 Name'),
        }
        assert set(addon2.translations[addon2.homepage_id]) == {
            ('en-us', 'https://example.com')
        }


def test_has_urls():
    content = 'a text <strong>without</strong> links'
    assert not amo.utils.has_urls(content)

    content = 'a <a href="http://example.com">link</a> with markup'
    assert amo.utils.has_urls(content)

    content = 'a http://example.com text link'
    assert amo.utils.has_urls(content)

    content = 'a badly markuped <a href="http://example.com">link'
    assert amo.utils.has_urls(content)


def test_walkfiles():
    basedir = tempfile.mkdtemp(dir=settings.TMP_PATH)
    subdir = tempfile.mkdtemp(dir=basedir)
    file1, file1path = tempfile.mkstemp(dir=basedir, suffix='_foo')
    file2, file2path = tempfile.mkstemp(dir=subdir, suffix='_foo')
    file3, file3path = tempfile.mkstemp(dir=subdir, suffix='_bar')

    # Only files ending with _foo.
    assert list(walkfiles(basedir, suffix='_foo')) == [file1path, file2path]
    # All files.
    all_files = list(walkfiles(basedir))
    assert len(all_files) == 3
    assert set(all_files) == {file1path, file2path, file3path}


def test_cached_property():
    callme = mock.Mock()

    class Foo:
        @cached_property
        def bar(self):
            callme()
            return 'value'

    foo = Foo()
    # Call twice...
    assert foo.bar == 'value'
    assert foo.bar == 'value'

    # Check that callme() was called only once.
    assert callme.call_count == 1


def test_set_writable_cached_property():
    callme = mock.Mock()

    class Foo:
        @cached_property
        def bar(self):
            callme()
            return 'original value'

    foo = Foo()
    foo.bar = 'new value'
    assert foo.bar == 'new value'

    # Check that callme() was never called, since we overwrote the prop value.
    assert callme.call_count == 0

    del foo.bar
    assert foo.bar == 'original value'
    assert callme.call_count == 1


@pytest.mark.parametrize('lang', settings.AMO_LANGUAGES)
def test_get_locale_from_lang(lang):
    """Make sure all languages in settings.AMO_LANGUAGES can be resolved."""
    locale = get_locale_from_lang(lang)
    lang_split = lang.split('-')

    assert isinstance(locale, Locale)
    assert locale.language == (
        lang_split[0] if lang not in LANGUAGES_NOT_IN_BABEL else 'en'
    )

    if '-' in lang and lang not in LANGUAGES_NOT_IN_BABEL:
        territory = lang_split[1]
        assert locale.territory == territory


@mock.patch('olympia.amo.utils.subprocess')
def test_pngcrush_image(subprocess_mock):
    subprocess_mock.Popen.return_value.communicate.return_value = ('', '')
    subprocess_mock.Popen.return_value.returncode = 0  # success
    assert pngcrush_image('/tmp/some_file.png')
    assert subprocess_mock.Popen.call_count == 1
    assert subprocess_mock.Popen.call_args_list[0][0][0] == [
        settings.PNGCRUSH_BIN,
        '-q',
        '-reduce',
        '-ow',
        '/tmp/some_file.png',
        '/tmp/some_file.crush.png',
    ]
    assert subprocess_mock.Popen.call_args_list[0][1] == {
        'stdout': subprocess_mock.PIPE,
        'stderr': subprocess_mock.PIPE,
    }

    # Make sure that exceptions for this are silent.
    subprocess_mock.Popen.side_effect = Exception
    assert not pngcrush_image('/tmp/some_other_file.png')


def test_utc_millesecs_from_epoch():
    with time_machine.travel('2018-11-18 06:05:04.030201', tick=False):
        timestamp = utc_millesecs_from_epoch()
    assert timestamp == 1542521104030

    future_now = datetime.datetime(2018, 11, 20, 4, 8, 15, 162342)
    timestamp = utc_millesecs_from_epoch(future_now)
    assert timestamp == 1542686895162

    new_timestamp = utc_millesecs_from_epoch(
        future_now + datetime.timedelta(milliseconds=42)
    )
    assert new_timestamp == timestamp + 42


def test_extract_colors_from_image():
    path = os.path.join(
        settings.ROOT, 'src/olympia/versions/tests/static_themes/weta.png'
    )
    expected = [
        {'h': 45, 'l': 158, 'ratio': 0.40547158773994313, 's': 34},
        {'h': 44, 'l': 94, 'ratio': 0.2812929380875291, 's': 28},
        {'h': 68, 'l': 99, 'ratio': 0.13200103391513734, 's': 19},
        {'h': 43, 'l': 177, 'ratio': 0.06251105336906689, 's': 93},
        {'h': 47, 'l': 115, 'ratio': 0.05938209966397758, 's': 60},
        {'h': 40, 'l': 201, 'ratio': 0.05934128722434598, 's': 83},
    ]
    assert extract_colors_from_image(path) == expected


class TestHttpResponseXSendFile(TestCase):
    def test_normalizes_path(self):
        path = '/some/../path/'
        response = HttpResponseXSendFile(request=None, path=path)
        assert response[settings.XSENDFILE_HEADER] == os.path.normpath(path)
        assert not response.has_header('Content-Disposition')

    def test_adds_etag_header(self):
        etag = '123'
        response = HttpResponseXSendFile(request=None, path='/', etag=etag)
        assert response.has_header('ETag')
        assert response['ETag'] == quote_etag(etag)

    def test_adds_content_disposition_header(self):
        response = HttpResponseXSendFile(request=None, path='/', attachment=True)
        assert response.has_header('Content-Disposition')
        assert response['Content-Disposition'] == 'attachment'


def test_images_are_small():
    """A test that will fail if we accidentally include a large image."""
    large_images = []
    img_path = os.path.join(settings.ROOT, 'static', 'img')
    for root, _dirs, files in os.walk(img_path):
        large_images += [
            os.path.join(root, name)
            for name in files
            if os.path.getsize(os.path.join(root, name)) > IMAGE_FILESIZE_MAX
        ]
    assert not large_images


class TestIsSafeUrl(TestCase):
    def test_enforces_https_when_request_is_secure(self):
        request = RequestFactory().get('/', secure=True)
        assert is_safe_url(f'https://{settings.DOMAIN}', request)
        assert not is_safe_url(f'http://{settings.DOMAIN}', request)

    def test_does_not_require_https_when_request_is_not_secure(self):
        request = RequestFactory().get('/', secure=False)
        assert is_safe_url(f'https://{settings.DOMAIN}', request)
        assert is_safe_url(f'http://{settings.DOMAIN}', request)

    def test_allows_domain(self):
        request = RequestFactory().get('/', secure=True)
        assert is_safe_url(f'https://{settings.DOMAIN}/foo', request)
        assert not is_safe_url('https://not-olympia.dev', request)

    def test_allows_with_allowed_hosts(self):
        request = RequestFactory().get('/', secure=True)
        foobaa_domain = 'foobaa.com'
        assert is_safe_url(
            f'https://{foobaa_domain}/foo', request, allowed_hosts=[foobaa_domain]
        )
        assert not is_safe_url(
            f'https://{settings.DOMAIN}', request, allowed_hosts=[foobaa_domain]
        )

    @override_settings(DOMAIN='mozilla.com', ADDONS_FRONTEND_PROXY_PORT='1234')
    def test_includes_host_for_proxy_when_proxy_port_setting_exists(self):
        request = RequestFactory().get('/')
        assert is_safe_url('https://mozilla.com:1234', request)
        assert not is_safe_url('https://mozilla.com:9876', request)

    @override_settings(DOMAIN='mozilla.com')
    def test_proxy_port_defaults_to_none(self):
        request = RequestFactory().get('/')
        assert is_safe_url('https://mozilla.com', request)
        assert not is_safe_url('https://mozilla.com:7000', request)


@pytest.mark.parametrize(
    'value, expected',
    [
        ('føǿ ', 'foo'),
        ('bär', 'bar'),
        ('b+är', 'bar'),
        ('Ali.ce', 'Alice'),
        ('Ⓖ𝑜𝕒𝔩', 'Goal'),
        ('Arg, Ⓖ𝑜𝕒𝔩+ 1', 'ArgGoal1'),
        ('\u2800', ''),
        ('Something\x7f\u20dfFishy', 'SomethingFishy'),
        ('Something\ufffcVery\U0001d140Fishy', 'SomethingVeryFishy'),
        ('қѺʍѕ', 'koms'),
        ('tЄctoniк', 'tectonik'),
        ('ωïnnϵr', 'winner'),
    ],
)
def test_normalize_string_for_name_checks(value, expected):
    assert normalize_string_for_name_checks(value) == expected


@pytest.mark.parametrize(
    'value, expected',
    [
        ('føǿ ', 'foó '),  # Decomposed accent (Mark) and whitespace are now kept
        ('bär', 'bär'),  # Accent (Mark) is now kept, we've decomposed the ä
        ('b+är', 'b+är'),  # Symbol and Accent are now kept, we've decomposed the ä
        ('Ali.ce', 'Alice'),  # Puncutation is gone
        ('Ⓖ𝑜𝕒𝔩', 'Goal'),  # Still normalized
        ('Arg, Ⓖ𝑜𝕒𝔩+ 1', 'Arg Goal+ 1'),  # Still normalized without punctuation
        ('\u2800', ''),  # Still gone because it's a special invisible char
        # Kept control char/mark
        ('Something\x7f\u20dfFishy', 'Something\x7f\u20dfFishy'),
        # We always remove special invisible chars even though they are not
        # part of the allowed categories
        ('Something\ufffcVery\U0001d140Fishy', 'SomethingVeryFishy'),
    ],
)
def test_normalize_string_for_name_checks_with_specific_category(value, expected):
    assert (
        normalize_string_for_name_checks(value, categories_to_strip=('P',)) == expected
    )


@pytest.mark.parametrize(
    'value, expected',
    [
        ('aBc', {'abc'}),
        ('\u0430bc', {'abc'}),
        ('l\u04300', {'iao', 'lao'}),
        ('𝐪1lt', {'qiit', 'qilt', 'qlit', 'qllt'}),
        ('bеta', {'beta'}),
        ('Zoom', {'zoom'}),
        ('ТЕСТ0n1𝓀', {'tectonik', 'tectonlk'}),
    ],
)
def test_generate_lowercase_homoglyphs_variants_for_string(value, expected):
    res = generate_lowercase_homoglyphs_variants_for_string(value)
    assert inspect.isgenerator(res)
    assert set(res) == expected


@pytest.mark.parametrize(
    'value, expected',
    [
        (1, '1/01/1'),
        (12, '2/12/12'),
        (123, '3/23/123'),
        (1234, '4/34/1234'),
        (123456789, '9/89/123456789'),
    ],
)
def test_id_to_path(value, expected):
    assert id_to_path(value) == expected


@pytest.mark.parametrize(
    'value, expected',
    [
        (1, '01/0001/1'),
        (12, '12/0012/12'),
        (123, '23/0123/123'),
        (1234, '34/1234/1234'),
        (123456, '56/3456/123456'),
        (123456789, '89/6789/123456789'),
    ],
)
def test_id_to_path_breadth(value, expected):
    assert id_to_path(value, breadth=2) == expected


def test_backup_storage_enabled():
    with override_settings(
        GOOGLE_APPLICATION_CREDENTIALS_STORAGE=None,
        GOOGLE_STORAGE_REPORTED_CONTENT_BUCKET=None,
    ):
        assert not backup_storage_enabled()
    with override_settings(
        GOOGLE_APPLICATION_CREDENTIALS_STORAGE='/something',
        GOOGLE_STORAGE_REPORTED_CONTENT_BUCKET=None,
    ):
        assert not backup_storage_enabled()
    with override_settings(
        GOOGLE_APPLICATION_CREDENTIALS_STORAGE='/something',
        GOOGLE_STORAGE_REPORTED_CONTENT_BUCKET='buck',
    ):
        assert backup_storage_enabled()


@mock.patch('google.cloud.storage.Client')
@override_settings(
    GOOGLE_APPLICATION_CREDENTIALS_STORAGE='/some/json',
    GOOGLE_STORAGE_REPORTED_CONTENT_BUCKET='some-bucket',
)
def test_backup_storage_setup(google_storage_client_mock):
    from_service_account_json_mock = (
        google_storage_client_mock.from_service_account_json
    )
    bucket_mock = from_service_account_json_mock.return_value.bucket
    blob_mock = bucket_mock.return_value.blob
    backup_file_name_remote = 'some_remöte_name.png'

    assert backup_storage_blob(backup_file_name_remote) == blob_mock.return_value

    assert from_service_account_json_mock.call_count == 1
    assert from_service_account_json_mock.call_args_list[0][0] == (
        settings.GOOGLE_APPLICATION_CREDENTIALS_STORAGE,
    )

    assert bucket_mock.call_count == 1
    assert bucket_mock.call_args_list[0][0] == (
        settings.GOOGLE_STORAGE_REPORTED_CONTENT_BUCKET,
    )
    assert blob_mock.call_count == 1
    assert blob_mock.call_args_list[0][0] == (backup_file_name_remote,)


@mock.patch('olympia.amo.utils.backup_storage_blob')
def test_copy_file_to_backup_storage(backup_storage_blob_mock):
    local_file_path = get_image_path('sunbird-small.png')
    with open(local_file_path, 'rb') as f:
        hash_ = hashlib.sha256(f.read())
    hash_.update(os.path.abspath(local_file_path).encode('utf-8'))
    expected_backup_file_name = f'{hash_.hexdigest()}.png'
    upload_from_filename_mock = (
        backup_storage_blob_mock.return_value.upload_from_filename
    )
    upload_from_filename_mock.return_value = expected_backup_file_name

    assert (
        copy_file_to_backup_storage(local_file_path, 'image/png')
        == expected_backup_file_name
    )
    assert backup_storage_blob_mock.call_count == 1
    assert backup_storage_blob_mock.call_args_list[0][0] == (expected_backup_file_name,)
    assert upload_from_filename_mock.call_count == 1
    assert upload_from_filename_mock.call_args_list[0][0] == (local_file_path,)
    assert upload_from_filename_mock.call_args_list[0][1] == {'if_generation_match': 0}


@mock.patch('olympia.amo.utils.backup_storage_blob')
def test_copy_file_to_backup_storage_precondition_failed(backup_storage_blob_mock):
    local_file_path = get_image_path('sunbird-small.png')
    with open(local_file_path, 'rb') as f:
        hash_ = hashlib.sha256(f.read())
    hash_.update(os.path.abspath(local_file_path).encode('utf-8'))
    expected_backup_file_name = f'{hash_.hexdigest()}.png'
    upload_from_filename_mock = (
        backup_storage_blob_mock.return_value.upload_from_filename
    )
    upload_from_filename_mock.side_effect = PreconditionFailed('File exists')

    assert (
        copy_file_to_backup_storage(local_file_path, 'image/png')
        == expected_backup_file_name
    )
    assert backup_storage_blob_mock.call_count == 1
    assert backup_storage_blob_mock.call_args_list[0][0] == (expected_backup_file_name,)
    assert upload_from_filename_mock.call_count == 1
    assert upload_from_filename_mock.call_args_list[0][0] == (local_file_path,)
    assert upload_from_filename_mock.call_args_list[0][1] == {'if_generation_match': 0}


@mock.patch('olympia.amo.utils.backup_storage_blob')
def test_create_signed_url_for_file_backup(backup_storage_blob_mock):
    backup_file_name = 'sômeremotefile.png'
    expected_signed_url = 'https://storage.example.com/fake-signed-url.png?foo=bar'
    generate_signed_url_mock = backup_storage_blob_mock.return_value.generate_signed_url
    generate_signed_url_mock.return_value = expected_signed_url
    assert create_signed_url_for_file_backup(backup_file_name) == expected_signed_url

    assert backup_storage_blob_mock.call_count == 1
    assert backup_storage_blob_mock.call_args_list[0][0] == (backup_file_name,)
    assert generate_signed_url_mock.call_count == 1
    assert generate_signed_url_mock.call_args_list[0][0] == ()
    assert generate_signed_url_mock.call_args_list[0][1] == {
        'expiration': datetime.timedelta(days=REPORTED_MEDIA_BACKUP_EXPIRATION_DAYS)
    }


@mock.patch('olympia.amo.utils.backup_storage_blob')
def test_download_file_contents_from_backup_storage(backup_storage_blob_mock):
    backup_file_name = 'sômeremotefile.png'
    expected_contents = b'Fake Content'
    download_as_bytes_mock = backup_storage_blob_mock.return_value.download_as_bytes
    download_as_bytes_mock.return_value = expected_contents
    assert (
        download_file_contents_from_backup_storage(backup_file_name)
        == expected_contents
    )
    assert backup_storage_blob_mock.call_count == 1
    assert backup_storage_blob_mock.call_args_list[0][0] == (backup_file_name,)
    assert download_as_bytes_mock.call_count == 1
