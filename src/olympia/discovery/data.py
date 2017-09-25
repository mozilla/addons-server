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
        self.is_recommendation = kwargs.get('is_recommendation', False)

    def __repr__(self):
        return 'DiscoItem(%s, %s, %s, %s, %s)' % (
            self.addon_id, self.addon_name, self.heading, self.description,
            self.type)


# At the moment the disco pane items are hardcoded in this file in the repos,
# which allows us to integrate in our translation workflow easily. Add-on ids
# are used instead of slugs to prevent any accidental replacement of a deleted
# add-on by another.
discopane_items = [
    # 'Pearlescent' theme.
    DiscoItem(addon_id=696234, type=amo.ADDON_PERSONA),

    # New Tab Override.
    DiscoItem(
        addon_id=626810,
        heading=_(u'Tab Customization {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Set the page you see every time you open a new tab.'),
            '</blockquote>')),

    # Emoji Cheatsheet.
    DiscoItem(
        addon_id=511962,
        heading=_(u'Up your emoji game {start_sub_heading}with '
                  u'{addon_name}{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Dozens of amazing emojis—always a click away.'),
            '</blockquote>')),

    # 'Dog Pichu' theme.
    DiscoItem(addon_id=265123, type=amo.ADDON_PERSONA),

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

    # 'Fall Painting' theme.
    DiscoItem(addon_id=644254, type=amo.ADDON_PERSONA),
]
