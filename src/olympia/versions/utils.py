import io
import math
import os
import re
import tempfile
from base64 import b64encode
from datetime import datetime, timedelta

from django.conf import settings
from django.utils.encoding import force_str
from django.utils.translation import gettext

import tinycss2
from PIL import Image
from tinycss2.color3 import parse_color

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
    # Image backgrounds are rendered as SVG <pattern>s (as opposed to the CSS
    # gradients handled by GradientBackground, see below).
    is_gradient = False

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


# CSS gradient functions we accept as `additional_backgrounds` entries. Firefox
# themes may use a `{'linear-gradient': '...'}` object instead of an image path.
GRADIENT_FUNCTIONS = frozenset(
    (
        'linear-gradient',
        'radial-gradient',
        'repeating-linear-gradient',
        'repeating-radial-gradient',
    )
)
# CSS `<side-or-corner>` keywords mapped to the equivalent gradient line angle,
# so `linear-gradient(to bottom, ...)` and `linear-gradient(180deg, ...)` share
# the same code path.
_SIDE_TO_ANGLE = {'top': 0, 'right': 90, 'bottom': 180, 'left': 270}
_CORNER_TO_ANGLE = {
    frozenset(('top', 'right')): 45,
    frozenset(('bottom', 'right')): 135,
    frozenset(('bottom', 'left')): 225,
    frozenset(('top', 'left')): 315,
}


def _strip_whitespace(tokens):
    return [token for token in tokens if token.type != 'whitespace']


def _split_on_commas(tokens):
    """Split a list of tinycss2 component values on top-level comma tokens."""
    segments, current = [], []
    for token in tokens:
        if token.type == 'literal' and token.value == ',':
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)
    return segments


def _parse_gradient_function(entry):
    """Turn an `additional_backgrounds` entry into a validated tinycss2 gradient
    function node, or return None if it isn't a valid CSS gradient.

    Entries that aren't image paths are expected to be dicts (JSON objects) with
    the CSS function name as the key and its parameters as the value, e.g.
    ``{'linear-gradient': 'to bottom, #FF6BBA 0%, #FFC999 50%'}``.
    """
    try:
        gradient_dict = dict(entry)
    except (TypeError, ValueError):
        return None
    # A gradient is described by a single `function: parameters` pair.
    if len(gradient_dict) != 1:
        return None
    ((name, params),) = gradient_dict.items()
    if not isinstance(name, str) or not isinstance(params, str):
        return None
    name = name.strip().lower()
    if name not in GRADIENT_FUNCTIONS:
        return None
    # Re-assemble the CSS declaration and let tinycss2 validate it: the result
    # must be a single, well-formed gradient function and nothing else (which
    # also rejects attempts to smuggle extra tokens in through the parameters).
    nodes = _strip_whitespace(tinycss2.parse_component_value_list(f'{name}({params})'))
    if len(nodes) != 1:
        return None
    func = nodes[0]
    if func.type != 'function' or func.lower_name != name:
        return None
    if any(argument.type == 'error' for argument in func.arguments):
        return None
    return func


def _parse_color_stops(segment):
    """Parse a gradient color-stop segment into a list of `(color, offset)` tuples,
    or return None if it isn't a valid color stop.

    A color stop is exactly one color optionally followed by one or two positions
    (CSS `<linear-color-stop>`; the two-position form is expanded into two stops).
    `None` covers both "this segment is a direction, not a stop" and "this stop is
    invalid"; the caller decides how to treat each case.
    """
    color_tokens, offsets = [], []
    for token in _strip_whitespace(segment):
        if token.type == 'percentage':
            offsets.append(token.value / 100.0)
        elif token.type in ('dimension', 'number'):
            # Absolute lengths (e.g. `20px`) and bare numbers can't be mapped to
            # an objectBoundingBox offset, so treat the stop as invalid rather
            # than silently rendering it at the wrong position.
            return None
        else:
            color_tokens.append(token)
    if len(color_tokens) != 1 or parse_color(color_tokens[0]) is None:
        return None
    if len(offsets) > 2:
        return None
    color = tinycss2.serialize(color_tokens).strip()
    if not offsets:
        return [(color, None)]
    return [(color, offset) for offset in offsets]


def _angle_to_vector(angle):
    """Map an axis-aligned CSS gradient line angle to SVG `linearGradient`
    coordinates in the default objectBoundingBox space (0deg points up, growing
    clockwise)."""
    radians = math.radians(angle % 360)
    x2 = 0.5 + 0.5 * math.sin(radians)
    y2 = 0.5 - 0.5 * math.cos(radians)
    return (round(1 - x2, 4), round(1 - y2, 4), round(x2, 4), round(y2, 4))


def _direction_to_angle(segment):
    """Return the gradient line angle described by a leading direction segment
    (e.g. `to bottom`, `45deg`), or None if the segment isn't a direction."""
    tokens = _strip_whitespace(segment)
    if not tokens:
        return None
    first = tokens[0]
    if first.type == 'ident' and first.lower_value == 'to':
        sides = {token.lower_value for token in tokens[1:] if token.type == 'ident'}
        if len(sides) == 1:
            return _SIDE_TO_ANGLE.get(next(iter(sides)))
        return _CORNER_TO_ANGLE.get(frozenset(sides))
    if first.type == 'dimension' and first.lower_unit in ('deg', 'grad', 'rad', 'turn'):
        return {
            'deg': first.value,
            'grad': first.value * 0.9,
            'rad': math.degrees(first.value),
            'turn': first.value * 360,
        }[first.lower_unit]
    if first.type == 'number' and first.value == 0:
        return 0
    return None


def _resolve_stop_offsets(offsets):
    """Fill in missing color-stop positions following the CSS rules: unset first
    and last stops default to 0% and 100%, runs of unset stops in between are
    evenly distributed, and offsets are clamped to a non-decreasing [0, 1]."""
    resolved = list(offsets)
    count = len(resolved)
    if resolved[0] is None:
        resolved[0] = 0.0
    if resolved[-1] is None:
        resolved[-1] = 1.0
    index = 0
    while index < count:
        if resolved[index] is None:
            end = index
            while resolved[end] is None:
                end += 1
            start_value, end_value = resolved[index - 1], resolved[end]
            steps = end - (index - 1)
            for step in range(index, end):
                resolved[step] = (
                    start_value
                    + (end_value - start_value) * (step - (index - 1)) / steps
                )
            index = end
        else:
            index += 1
    for index in range(1, count):
        resolved[index] = max(resolved[index], resolved[index - 1])
    return [min(1.0, max(0.0, value)) for value in resolved]


class GradientBackground:
    """A CSS gradient `additional_backgrounds` entry, rendered as an SVG
    `<linearGradient>`/`<radialGradient>` in the theme preview."""

    is_gradient = True

    def __init__(self, stops, angle, is_radial):
        self.is_radial = is_radial
        # Only linear gradients use a gradient vector; radial gradients are
        # rendered centered and the template never reads these coordinates.
        if not is_radial:
            self.x1, self.y1, self.x2, self.y2 = _angle_to_vector(angle)
        offsets = _resolve_stop_offsets([offset for _, offset in stops])
        self.stops = [
            {'color': color, 'offset': round(offset, 4)}
            for (color, _), offset in zip(stops, offsets, strict=True)
        ]


def parse_gradient_background(entry):
    """Build a GradientBackground from an `additional_backgrounds` entry, or
    return None if it isn't a CSS gradient we can faithfully render.

    To avoid showing previews that diverge from how the browser paints the theme,
    anything we can't represent exactly is rejected (and therefore not rendered):
    invalid directions or color stops, absolute-length stop positions, and
    non-axis-aligned linear gradients (which the preview's objectBoundingBox space
    would skew because of its aspect ratio).
    """
    func = _parse_gradient_function(entry)
    if func is None:
        return None
    is_radial = 'radial' in func.lower_name
    segments = _split_on_commas(func.arguments)
    if not segments:
        return None
    angle = 180  # CSS default direction is `to bottom`.
    stops = []
    # A leading segment that isn't a color stop is the gradient's direction (for
    # linear gradients) or shape/position (for radial gradients).
    first = _parse_color_stops(segments[0])
    if first is None:
        if not is_radial:
            angle = _direction_to_angle(segments[0])
            if angle is None or angle % 90 != 0:
                return None
    else:
        stops.extend(first)
    # Every remaining segment must be a valid color stop, otherwise the whole
    # gradient is invalid CSS and we reject it.
    for segment in segments[1:]:
        parsed = _parse_color_stops(segment)
        if parsed is None:
            return None
        stops.extend(parsed)
    if len(stops) < 2:
        return None
    return GradientBackground(stops, angle, is_radial=is_radial)


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
