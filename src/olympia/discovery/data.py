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
        heading=_('Block ads {start_sub_heading}with {addon_name}'
                  '{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _('“This add-on is amazing. Blocks all annoying ads. 5 stars.”'),
            '<cite>— rany</cite>',
            '</blockquote')),

    DiscoItem(
        addon_id=287841,
        heading=_('Take screenshots {start_sub_heading}with {addon_name}'
                  '{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _('“The best. Very easy to use.”'),
            '<cite>— meetdak</cite>',
            '</blockquote')),

    DiscoItem(addon_id=111435),

    DiscoItem(
        addon_id=511962,
        heading=_('Up your emoji game {start_sub_heading}with {addon_name}'
                  '{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _('“Very simple interface and easy to use. Thank you.”'),
            '<cite>— shadypurple</cite>',
            '</blockquote')),

    DiscoItem(
        addon_id=3006,
        heading=_('Download videos {start_sub_heading}with {addon_name}'
                  '{end_sub_heading}'),
        description=string_concat(
            '<blockquote>',
            _('“Download videos in a single click.”'),
            '<cite>— Carpe Diem</cite>',
            '</blockquote')),

    DiscoItem(addon_id=686505),

    DiscoItem(addon_id=345284),

]
