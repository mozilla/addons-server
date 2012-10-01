from tower import ugettext_lazy as _


APP_STEPS = [
    ('terms', _('Developer Agreement')),
    ('manifest', _('Submit')),
    ('details', _('Details')),
    ('done', _('Finished!')),
]
APP_STEPS_TITLE = dict(APP_STEPS)

# The sizes for the image assets for apps.
APP_IMAGE_SIZES = [
    {'size': (32, 32),
     'has_background': False,
     'required': False,
     'slug': 'featured_tile',
     'name': 'Featured Tile',
     'description': _("The icon shown when your app is featured at the top of "
                      "category landing pages.")},
    {'size': (106, 106),
     'has_background': False,
     'required': False,
     'slug': 'mobile_tile',
     'name': 'Mobile Tile',
     'description': _("The image used for the app's tile in the mobile "
                      "Marketplace.")},
    {'size': (150, 130),
     'has_background': False,
     'required': False,
     'slug': 'desktop_tile',
     'name': 'Desktop Tile',
     'description': _("The image used for the app's tile in the desktop "
                      "Marketplace.")},
]
