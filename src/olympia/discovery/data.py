# -*- coding: utf-8 -*-
from django.utils.translation import string_concat, ugettext_lazy as _

from olympia import amo


class DiscoItem(object):
    def __init__(self, *args, **kwargs):
        self.addon_id = kwargs.get('addon_id')
        self.addon_name = kwargs.get('addon_name')
        self.heading = kwargs.get('heading')
        self.description = kwargs.get('description')
        self.type = kwargs.get('type', amo.ADDON_EXTENSION)

    def __repr__(self):
        return 'DiscoItem(%s, %s, %s, %s, %s)' % (
            self.addon_id, self.addon_name, self.heading, self.description,
            self.type)


# At the moment the disco pane items are hardcoded in this file in the repos,
# which allows us to integrate in our translation workflow easily. Add-on ids
# are used instead of slugs to prevent any accidental replacement of a deleted
# add-on by another.
discopane_items = [
    # 'c o l o r s' theme.
    DiscoItem(addon_id=61230, addon_name='Colors', type=amo.ADDON_PERSONA),

    # Privacy Badger
    DiscoItem(
        addon_id=506646,
        heading=_(u'Stop sneaky trackers {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Block invisible trackers and spying ads that follow you '
              u'around the Web.'),
            '</blockquote>')),

    # LanguageTool Grammar Checker
    DiscoItem(
        addon_id=708770,
        heading=_(u'Improve your writing {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Supporting 25+ languages, this extension puts a proofreader '
              u'right in your browser.'),
            '</blockquote>')),

    # 'ibbis persona' theme.
    DiscoItem(addon_id=20628, addon_name='Ibbis Persona',
              type=amo.ADDON_PERSONA),

    # Awesome Screenshot Plus
    DiscoItem(
        addon_id=287841,
        heading=_(u'Take screenshots {start_sub_heading}with '
                  u'{addon_name}{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'More than just screenshots, Awesome Screenshot Plus lets you '
              u'annotate images with text and graphics. Storing and sharing '
              u'files is a breeze.'),
            '</blockquote>')),

    # Enhancer for YouTube
    DiscoItem(
        addon_id=700308,
        heading=_(u'Improve videos {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Enjoy a suite of new YouTube features, like cinema mode, '
              u'ad blocking, auto-play control, and more.'),
            '</blockquote>')),

    # 'two fireflies' theme.
    DiscoItem(addon_id=625990, addon_name='Two Fireflies',
              type=amo.ADDON_PERSONA),
]
