import django
from django.conf import settings
from jinja2.ext import babel_extract


# List of settings jinja2.ext.babel_extract() cares about and that are safe
# to pass as options as a result.
RELEVANT_SETTINGS = [
    'block_start_string',
    'block_end_string',
    'variable_start_string',
    'variable_end_string',
    'comment_start_string',
    'comment_end_string',
    'line_statement_prefix',
    'line_comment_prefix',
    'trim_blocks',
    'lstrip_blocks',
    'keep_trailing_newline',
    'extensions',
]


def generate_option(value):
    """
    Generate option to pass to babel_extract() from a TEMPLATES['OPTION'] value
    setting.

    babel_extract() options are meant to be coming from babel config files, so
    everything is based on strings.
    """
    if isinstance(value, bool):
        return 'true' if value else 'false'
    elif isinstance(value, (list, tuple)):
        return ','.join(value)
    return value


def extract_jinja(fileobj, keywords, comment_tags, options):
    """
    Wrapper around jinja2's babel_extract() that sets the relevant options by
    looking at our django settings.
    """
    # django needs to be configured for the jinja extensions to be imported,
    # since at least one imports our models.
    django.setup()

    for TEMPLATE in settings.TEMPLATES:
        if TEMPLATE.get('NAME') == 'jinja2':
            overrides = {
                key: generate_option(TEMPLATE['OPTIONS'][key])
                for key in RELEVANT_SETTINGS
                if key in TEMPLATE['OPTIONS']
            }
            options.update(overrides)
            # Special case: `trimmed` is configured through an environment policy,
            # but babel_extract() considers it's an option.
            options['trimmed'] = generate_option(
                TEMPLATE['OPTIONS'].get('policies', {}).get('ext.i18n.trimmed', False)
            )
            # Also, never be silent, that would hide exceptions that are almost
            # certainly bad news.
            options['silent'] = False
            break

    return babel_extract(fileobj, keywords, comment_tags, options)
