from tower import ugettext_lazy as _


APP_STEPS = [
    ('terms', _('Agreement')),
    ('manifest', _('Submit')),
    ('details', _('Details')),
    ('done', _('Done!')),
    # ('next_steps', _('Next Steps')),
]
APP_STEPS_TITLE = dict(APP_STEPS)

# Preview sizes in the format (width, height, type)
APP_PREVIEW_MINIMUMS = (320, 480)
APP_PREVIEW_SIZES = [
    (180, 270, 'mobile'),
    (700, 1050, 'full'),  # Because it's proportional, that's why.
]

MAX_PACKAGED_APP_SIZE = 100 * 1024 * 1024  # 100MB
