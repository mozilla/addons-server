# -*- coding: utf-8 -*-
from django.utils.translation import string_concat, ugettext_lazy as _


class DiscoItem(object):
    def __init__(self, *args, **kwargs):
        self.addon_id = kwargs.get('addon_id')
        self.addon_name = kwargs.get('addon_name')
        self.heading = kwargs.get('heading')
        self.description = kwargs.get('description')

# At the moment the disco pane items are hardcoded in this file in the repos,
# which allows us to integrate in our translation workflow easily.
discopane_items = [
    # Theme: Aurora Australis
    DiscoItem(addon_id=49331),

    # uBlock Origin
    DiscoItem(
        addon_id=607454,
        heading=_(u'Block ads {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'A lightweight and effective ad blocker. uBlock Origin '
              u'enforces thousands of content filters without chewing up a '
              u'bunch of memory.'),
            '</blockquote>')),

    # Awesome Screenshot Plus - Capture, Annotate & More
    DiscoItem(
        addon_id=287841,
        heading=_(u'Take screenshots {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'So much more than just a screenshot tool, this add-on also '
              u'lets you edit, annotate, and share images.'),
            '</blockquote>')),

    # Theme: Snow Style
    DiscoItem(addon_id=68349, addon_name=u'Snow Style'),

    # OmniSidebar
    DiscoItem(
        addon_id=296534,
        heading=_(u'Easily access bookmarks {start_sub_heading}with '
                  u'{addon_name}{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Are you constantly scrolling through your bookmarks? '
              u'Bring your lists into view with a single, simple gesture.'),
            '</blockquote>')),

    # Video DownloadHelper
    DiscoItem(
        addon_id=3006,
        heading=_(u'Download videos {start_sub_heading}with {addon_name}'
                  u'{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _(u'Want an easy way to download videos to watch offline or save '
              u'for later? Video DownloadHelper works beautifully with all '
              u'major streaming sites like YouTube, Facebook, Vimeo, Twitch, '
              u'and others.'),
            '</blockquote>')),

    # Theme: My Vinyl
    DiscoItem(addon_id=125478),
]
