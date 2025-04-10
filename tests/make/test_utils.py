from scripts.utils import (
    join_image_tag,
    parse_docker_tag,
)
from tests import override_env
from tests.make import BaseTestClass


@override_env()
class TestEnv(BaseTestClass):
    pass


@override_env()
class TestResolveImageTag(BaseTestClass):
    def setUp(self):
        super().setUp()
        custom_image = 'image/name'
        custom_version = 'custom-version'
        custom_digest = (
            '124b44bfc9ccd1f3cedf4b592d4d1e8bddb78b51ec2ed5056c52d3692baebc19'
        )
        self.valid_tags = [
            (
                f'{custom_image}:{custom_version}@sha256:{custom_digest}',
                custom_image,
                custom_version,
                custom_digest,
            ),
            (
                f'{custom_version}@sha256:{custom_digest}',
                'mozilla/addons-server',
                custom_version,
                custom_digest,
            ),
            (f'{custom_image}:{custom_version}', custom_image, custom_version, None),
        ]
        self.invalid_tags = [
            f'{custom_image}@digest',  # missing version
            '',  # missing image and version
            f'{custom_image}:',  # missing version
            f':{custom_version}',  # missing image
            f'{custom_image}:version:',  # invalid version
            f'{custom_image}:version@',  # missing digest
            f'{custom_image}@sha256:invalid',  # Invalid digest length
            f'@sha256:{custom_digest}',  # Missing image and version
            f'{custom_image}:version@sha256:',  # Missing digest value
            f'{custom_image}:ver$ion',  # Invalid version chars
            f'{custom_image}:.version',  # Version starts with .
            f'{custom_image}:-version',  # Version starts with -
            f'{custom_image}:{"x" * 129}',  # Version too long
        ]

    def assert_tag(
        self,
        input: str,
        image: str,
        version: str,
        digest: str,
    ):
        result = parse_docker_tag(input)
        self.assertEqual(result[0], join_image_tag(image, version, digest))
        self.assertEqual(result[1], image)
        self.assertEqual(result[2], version)
        self.assertEqual(result[3], digest)

    def test_invalid_tag_should_raise(self):
        for tag in self.invalid_tags:
            with self.subTest(tag=tag):
                with self.assertRaises(ValueError):
                    parse_docker_tag(tag)

    def test_valid_tags(self):
        for tag, image, version, digest in self.valid_tags:
            with self.subTest(tag=tag, image=image, version=version, digest=digest):
                self.assert_tag(
                    tag,
                    image,
                    version,
                    digest,
                )


class TestSetGetEnv(BaseTestClass):
    def test_set_and_getenv_file(self):
        self.env.write_env_file({'TEST': 'test'})
        self.assertEqual(self.env.get('TEST'), 'test')

    @override_env()
    def test_get_value_defuault(self):
        self.assertEqual(self.env.get('TEST', 'default'), 'default')

    @override_env()
    def test_get_value_override_file(self):
        self.env.write_env_file({'TEST': 'file'})
        self.assertEqual(self.env.get('TEST', 'default'), 'file')

    @override_env(TEST='env')
    def test_get_value_override_env(self):
        self.assertEqual(self.env.get('TEST', 'default'), 'env')
