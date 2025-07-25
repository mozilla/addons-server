import io
import os
import re
import tempfile
from base64 import b64encode
from datetime import datetime, timedelta

from django.conf import settings
from django.utils.encoding import force_str
from django.utils.translation import gettext

from PIL import Image

from olympia import amo
from olympia.amo.utils import convert_svg_to_png
from olympia.constants.reviewers import (
    REVIEWER_STANDARD_REVIEW_TIME,
)
from olympia.core import logger
from olympia.zadmin.models import get_config


log = logger.getLogger('z.versions.utils')


def get_next_version_number(addon):
    from .models import Version

    if not addon:
        return '1.0'
    last_version = Version.unfiltered.filter(addon=addon).order_by('id').last()

    version_counter = 1
    while True:
        next_version = '%s.0' % (last_version.version.vparts[0].a + version_counter)
        if not Version.unfiltered.filter(addon=addon, version=next_version).exists():
            return next_version
        else:
            version_counter += 1


def write_svg_to_png(svg_content, out):
    # when settings.DEBUG is on (i.e. locally) don't delete the svgs.
    tmp_args = {
        'dir': settings.TMP_PATH,
        'mode': 'wb',
        'suffix': '.svg',
        'delete': not settings.DEBUG,
    }
    with tempfile.NamedTemporaryFile(**tmp_args) as temporary_svg:
        temporary_svg.write(svg_content)
        temporary_svg.flush()
        return convert_svg_to_png(temporary_svg.name, out)


SVG_DIMENSIONS_REGEX = rb'(?=.* width="(?P<width>\d+)")(?=.* height="(?P<height>\d+)")'


def encode_header(header_blob, file_ext):
    try:
        if file_ext == '.svg':
            dimensions = re.search(SVG_DIMENSIONS_REGEX, header_blob).groupdict()
            width = int(dimensions['width'])
            height = int(dimensions['height'])
            img_format = 'svg+xml'
        else:
            with Image.open(io.BytesIO(header_blob)) as header_image:
                (width, height) = header_image.size
                img_format = header_image.format.lower()
        src = 'data:image/{};base64,{}'.format(
            img_format,
            force_str(b64encode(header_blob)),
        )
    except (OSError, ValueError, TypeError, AttributeError) as err:
        log.info(err)
        return (None, 0, 0)
    return (src, width, height)


class AdditionalBackground:
    @classmethod
    def split_alignment(cls, alignment):
        alignments = alignment.split()
        # e.g. "center top"
        if len(alignments) >= 2:
            return (alignments[0], alignments[1])
        elif len(alignments) == 1:
            # e.g. "left", which is the same as 'left center'
            if alignments[0] in ['left', 'right']:
                return (alignments[0], 'center')
            # e.g. "top", which is the same as 'center top'
            else:
                return ('center', alignments[0])
        else:
            return ('', '')

    def __init__(self, path, alignment, tiling, background):
        # If there an unequal number of alignments or tiling to srcs the value
        # will be None so use defaults.
        self.alignment = (alignment or 'right top').lower()
        self.tiling = (tiling or 'no-repeat').lower()
        file_ext = os.path.splitext(path)[1]
        self.src, self.width, self.height = encode_header(background, file_ext)

    def calculate_pattern_offsets(self, svg_width, svg_height):
        align_x, align_y = self.split_alignment(self.alignment)

        if align_x == 'right':
            self.pattern_x = svg_width - self.width
        elif align_x == 'center':
            self.pattern_x = (svg_width - self.width) // 2
        else:
            self.pattern_x = 0
        if align_y == 'bottom':
            self.pattern_y = svg_height - self.height
        elif align_y == 'center':
            self.pattern_y = (svg_height - self.height) // 2
        else:
            self.pattern_y = 0

        if self.tiling in ['repeat', 'repeat-x'] or self.width > svg_width:
            self.pattern_width = self.width
        else:
            self.pattern_width = svg_width
        if self.tiling in ['repeat', 'repeat-y'] or self.height > svg_height:
            self.pattern_height = self.height
        else:
            self.pattern_height = svg_height


DEPRECATED_COLOR_TO_CSS = {
    'toolbar_text': 'bookmark_text',
    'accentcolor': 'frame',
    'textcolor': 'tab_background_text',
}


def process_color_value(prop, value):
    prop = DEPRECATED_COLOR_TO_CSS.get(prop, prop)
    if isinstance(value, list) and len(value) == 3:
        return prop, 'rgb(%s,%s,%s)' % tuple(value)
    # strip out spaces because jquery.minicolors chokes on them
    return prop, str(value).replace(' ', '')


def get_review_due_date(starting=None, default_days=REVIEWER_STANDARD_REVIEW_TIME):
    generator = get_staggered_review_due_date_generator(
        starting=starting,
        initial_days_delay=default_days,
        # We send a dummy target per day just to avoid the database query for
        # the staggering which we don't need here as we only want a single due
        # date.
        target_per_day=1,
    )
    return next(generator)


def get_staggered_review_due_date_generator(
    *,
    starting=None,
    initial_days_delay=REVIEWER_STANDARD_REVIEW_TIME,
    target_per_day=None,
):
    starting = (starting or datetime.now()).replace(microsecond=0)
    # if starting falls on the weekend, move it to Monday morning.
    if starting.weekday() in (5, 6):
        starting = starting.replace(hour=9) + timedelta(days=(7 - starting.weekday()))

    due_date = starting + timedelta(days=initial_days_delay)

    if target_per_day is None:
        target_per_day = get_config(amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY)
    stagger = 24 / target_per_day

    while True:
        # if due date falls on or passes over a weekend, add on 2 days.
        if due_date.weekday() in (5, 6) or due_date.weekday() < starting.weekday():
            due_date += timedelta(days=2)
        yield due_date
        due_date += timedelta(hours=stagger)
        # When we ask the generator for more than a single date, we no longer
        # care about the due date passing over a week-end when compared to the
        # starting date (since we're arbitrarily staggering the dates in the
        # future), so fake the starting date from now on to prevent that check
        # above from triggering an additional unwanted delay.
        starting = due_date


def validate_version_number_does_not_exist(addon, version_string):
    """Returns an error string if `version_string` already exists for any version of
    this add-on."""
    from .models import Version

    # Make sure we don't already have this version.
    existing_versions = Version.unfiltered.filter(addon=addon, version=version_string)
    if existing_versions.exists():
        if existing_versions[0].deleted:
            msg = gettext('Version {version_string} was uploaded before and deleted.')
        else:
            msg = gettext('Version {version_string} already exists.')
        return msg.format(version_string=version_string)


def validate_version_number_is_gt_latest_signed_listed_version(addon, version_string):
    """Returns an error string if `version_string` isn't greater than the current
    approved listed version. Doesn't apply to langpacks."""
    if (
        addon
        and addon.type != amo.ADDON_LPAPP
        and (
            latest_version_string := addon.versions(manager='unfiltered_for_relations')
            .filter(channel=amo.CHANNEL_LISTED, file__is_signed=True)
            .order_by('created')
            .values_list('version', flat=True)
            .last()
        )
        and latest_version_string >= version_string
    ):
        msg = gettext(
            'Version {version_string} must be greater than the previous approved '
            'version {previous_version_string}.'
        )
        return msg.format(
            version_string=version_string,
            previous_version_string=latest_version_string,
        )
