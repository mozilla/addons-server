def default_from_schema(schema):
    """Return a dict with default values filled in from a JSON schema.

    Only supports the flat objects."""
    obj = {}
    if schema.get('type') != 'object':
        return obj
    for key in schema.get('keys', []):
        if 'default' in schema['keys'][key]:
            obj[key] = schema['keys'][key]['default']
    return obj
