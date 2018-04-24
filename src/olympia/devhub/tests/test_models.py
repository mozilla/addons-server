from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.devhub.models import BlogPost
from olympia.files.models import File
from olympia.versions.models import Version


class TestVersion(TestCase):
    fixtures = ['base/users', 'base/addon_3615', 'base/thunderbird']

    def setUp(self):
        super(TestVersion, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = Version.objects.get(pk=81551)
        self.file = File.objects.get(pk=67442)

    def test_version_delete_status_null(self):
        self.version.delete()
        assert self.addon.versions.count() == 0
        assert Addon.objects.get(pk=3615).status == amo.STATUS_NULL

    def _extra_version_and_file(self, status):
        version = Version.objects.get(pk=81551)

        version_two = Version(addon=self.addon,
                              license=version.license,
                              version='1.2.3')
        version_two.save()

        file_two = File(status=status, version=version_two)
        file_two.save()
        return version_two, file_two

    def test_version_delete_status_unreviewed(self):
        self._extra_version_and_file(amo.STATUS_AWAITING_REVIEW)

        self.version.delete()
        assert self.addon.versions.count() == 1
        assert Addon.objects.get(id=3615).status == amo.STATUS_NOMINATED

    def test_file_delete_status_null(self):
        assert self.addon.versions.count() == 1
        self.file.delete()
        assert self.addon.versions.count() == 1
        assert Addon.objects.get(pk=3615).status == amo.STATUS_NULL

    def test_file_delete_status_null_multiple(self):
        version_two, file_two = self._extra_version_and_file(amo.STATUS_NULL)
        self.file.delete()
        assert self.addon.status == amo.STATUS_PUBLIC
        file_two.delete()
        assert self.addon.status == amo.STATUS_NULL


class TestBlogPosts(TestCase):

    def test_blog_posts(self):
        BlogPost.objects.create(title='hi')
        bp = BlogPost.objects.all()
        assert bp.count() == 1
        assert bp[0].title == "hi"
