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
    {'size': (106, 106),
     'required': False,
     'slug': 'mobile_tile',
     'name': 'Mobile Tile',
     'description': _("The image that's actually used for the app's tile in "
                      "the Marketplace.")},
    {'size': (150, 130),
     'required': False,
     'slug': 'desktop_tile',
     'name': 'Desktop Tile',
     'description': _("The image used for the app's tile in the desktop "
                      "Marketplace.")},
]
