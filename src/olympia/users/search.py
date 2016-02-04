from operator import attrgetter


def extract(user):
    # These all get converted into unicode.
    unicode_attrs = ('email', 'username', 'display_name', 'bio',
                     'homepage', 'location', 'occupation')
    d = dict(zip(unicode_attrs,
                 [unicode(a) for a in attrgetter(*unicode_attrs)(user) if a]))
    attrs = ('id', 'deleted')
    d.update(dict(zip(attrs, attrgetter(*attrs)(user))))
    return d
