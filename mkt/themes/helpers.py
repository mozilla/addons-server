import jinja2

from jingo import register


#TODO: This is pretty much a copy of addons/helpers.py (duplicate code)
@register.inclusion_tag('themes/includes/theme_preview.html')
@jinja2.contextfunction
def theme_preview(context, persona, size='large', linked=True, extra=None,
                    details=False, title=False, caption=False, url=None):
    preview_map = {'large': persona.preview_url,
                   'small': persona.thumb_url}
    addon = persona.addon
    c = dict(context.items())
    c.update({'persona': persona, 'addon': addon, 'linked': linked,
              'size': size, 'preview': preview_map[size], 'extra': extra,
              'details': details, 'title': title, 'caption': caption,
              'url_': url})
    return c
