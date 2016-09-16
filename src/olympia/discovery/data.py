# -*- coding: utf-8 -*-
from django.utils.translation import string_concat, ugettext_lazy as _


class DiscoItem(object):
    def __init__(self, *args, **kwargs):
        self.addon_id = kwargs.get('addon_id')
        self.heading = kwargs.get('heading')
        self.description = kwargs.get('description')

# At the moment the disco pane items are hardcoded in this file in the repos,
# which allows us to integrate in our translation workflow easily.
discopane_items = [
    DiscoItem(addon_id=362876),

    DiscoItem(
        addon_id=1865,
        heading=_(u'Block ads {start_sub_heading}with {addon_name}'
                  '{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Remove blaring ads and make the Web run smoother with ')
              u'Adblock Plus.')
            '</blockquote>')),

    DiscoItem(
        addon_id=287841,
        heading=_(u'Take screenshots {start_sub_heading}with {addon_name}'
                  '{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'So much more than just a screenshot tool, this add-on also '
              u'lets you edit, annotate, and share images.'),
            '</blockquote>')),

    DiscoItem(addon_id=111435),

    DiscoItem(
        addon_id=511962,
        heading=_(u'Up your emoji game {start_sub_heading}with {addon_name}'
                  '{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Get instant access to a bunch of great emojis and easily use '
              u'them on popular sites like Facebook, Twitter, Google+, and '
              u'others.'),
            '</blockquote>')),

    DiscoItem(
        addon_id=3006,
        heading=_(u'Download videos {start_sub_heading}with {addon_name}'
                  '{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Want an easy way to download videos to watch offline or save '
              u'for later? Video DownloadHelper works beautifully with all '
              u'major streaming sites like YouTube, Facebook, Vimeo, Twitch, '
              u'and others.'),
            '</blockquote>')),

    DiscoItem(addon_id=686505),
]
