from django import template


register = template.Library()


@register.simple_tag
def assay_url(addon_guid, version_string, filepath=None):
    url = f'vscode://mozilla.assay/review/{addon_guid}/{version_string}'
    if filepath:
        url = f'{url}?path={filepath}'
    return url
