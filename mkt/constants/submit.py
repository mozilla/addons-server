from tower import ugettext_lazy as _


APP_STEPS = [
    ('terms', _('Agreement')),
    ('manifest', _('Submit')),
    ('details', _('Details')),
    ('done', _('Done!')),
]
APP_STEPS_TITLE = dict(APP_STEPS)

# The sizes for the image assets for apps.
APP_IMAGE_SIZES = [
    {'size': (32, 32),
     'has_background': False,
     'required': False,
     'slug': 'featured_tile',
     'name': _('Featured Tile'),
     'description': _("The icon shown when your app is featured at the top of "
                      "category landing pages.")},
    {'size': (106, 106),
     'has_background': False,
     'required': False,
     'slug': 'mobile_tile',
     'name': _('Mobile Tile'),
     'description': _("The image used for the app's tile in the mobile "
                      "Marketplace.")},
    {'size': (150, 130),
     'has_background': False,
     'required': False,
     'slug': 'desktop_tile',
     'name': _('Desktop Tile'),
     'description': _("The image used for the app's tile in the desktop "
                      "Marketplace.")},
]

# Preview sizes in the format (width, height, type)
APP_PREVIEW_MINIMUMS = (320, 480)
APP_PREVIEW_SIZES = [
    (180, 270, 'mobile'),
    (700, 1050, 'full'),  # Because it's proportional, that's why.
]

MAX_PACKAGED_APP_SIZE = 50 * 1024 * 1024  # 50MB
