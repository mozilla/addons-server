# -*- coding: utf-8 -*-


def generate_translations(item):
    """Generate French and Spanish translations for the given `item`."""
    fr_prefix = u'(français) '
    es_prefix = u'(español) '
    oldname = unicode(item.name)
    item.name = {
        'en': oldname,
        'fr': fr_prefix + oldname,
        'es': es_prefix + oldname,
    }
    item.save()
