import os
import re
from pathlib import Path


class Env:
    def __init__(self, env_file: Path):
        self.env_file = env_file

    def from_file(self) -> dict[str, str]:
        if not self.env_file.exists():
            return {}

        return {
            key: value.strip('"')
            for key, value in (
                line.strip().split('=', 1)
                for line in self.env_file.read_text().splitlines()
            )
        }

    def from_env(self) -> dict[str, str]:
        return os.environ

    def write_env_file(self, values: dict[str, str]):
        with self.env_file.open('w') as f:
            for key, value in values.items():
                f.write(f'{key}="{value}"\n')

        print(f'Wrote to {self.env_file.as_posix()}: \n')
        print(f'{self.env_file.read_text()}')

    def get(
        self,
        key: str,
        default_value: str = None,
        from_file: bool = True,
        type: type = None,
    ):
        value = default_value

        if key in (env := self.from_env()):
            value = env[key]
        elif from_file and key in (file := self.from_file()):
            value = file[key]

        if type is not None:
            value = type(value)

        return value


DOCKER_TAG_REGEX = re.compile(
    r"""
    ^                           # Start of the string
    (?P<image>                  # Image name group
        [^:@]+                  # Match anything except : and @ characters
    )
    (?:                         # Version group (required if : present)
        :                       # Version separator
        (?P<version>            # Capture group 'version'
            (?![\.-])           # Version cannot start with . or -
            [a-zA-Z0-9_.-]{1,128} # Version characters
        )
    )?                          # Version is optional if no : present
    (?:                         # Optional Digest group
        @sha256:                # Digest separator
        (?P<digest>[a-fA-F0-9]{64}) # Capture group 'digest' (hex chars)
    )?                          # Digest is optional
    $                           # End of the string
    """,
    re.VERBOSE,
)


def join_image_tag(image, version, digest):
    tag = f'{image}:{version}'
    if digest:
        tag += f'@sha256:{digest}'
    return tag


def parse_docker_tag(tag: str) -> tuple[str, str, str | None, str | None]:
    """
    Resolve the image tag from the .env file and or environment variables.
    1) base tag is the local tag
    2) can be overriden by the DOCKER_TAG in the .env file
    3) can be overriden by the DOCKER_TAG environment variable
    - DOCKER_TAG can specify:
        - a full tag (image:version@sha256:digest)
        - a version and a digest (version@sha256:digest)
        - a version (version)

    Returns: ['image:version@digest!', 'image!', 'version!', 'digest']
    """
    match = DOCKER_TAG_REGEX.match(tag)

    if not match:
        raise ValueError(f'Invalid image tag: {tag}')

    image = match.group('image')
    version = match.group('version')
    digest = match.group('digest')

    # Handle cases where only a version (or version@digest) is provided,
    # assuming it applies to the default image. The regex captures the
    # version/version@digest part as 'image' if no ':' is present initially.
    if image and not version and not digest and ':' not in image and '@' not in image:
        # Input was likely just 'some-version'
        version = image
        image = 'mozilla/addons-server'  # Default image name
    elif image and not version and digest and ':' not in image:
        # Input was likely 'some-version@sha256:...'
        version = image  # The part before '@' is the version
        image = 'mozilla/addons-server'  # Default image name

    # Validate: If a digest is present, a version must also be present.
    if digest and not version:
        raise ValueError(
            f'Invalid image tag: {tag} '
            '(when specifying a digest, a version is required)'
        )

    # if version and ':' in version:
    #     raise ValueError(f'Invalid image tag: "{tag}" (version cannot contain ":")')

    full_tag = join_image_tag(image, version, digest)
    return full_tag, image, version, digest
