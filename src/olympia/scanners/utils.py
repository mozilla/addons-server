import jsonschema


SCANNER_RESULTS_SCHEMA = {
    'type': 'object',
    'required': ['version', 'matchedRules'],
    'properties': {
        'version': {'type': 'string'},
        'matchedRules': {
            'type': 'array',
            'items': {'type': 'string'},
        },
        'annotations': {
            'type': 'object',
            'additionalProperties': {
                'type': 'array',
                'items': {'type': 'object'},
            },
        },
    },
}


def validate_scanner_results(results):
    """Raise a `ValueError` when webhook scanner results are invalid."""
    try:
        jsonschema.validate(results, SCANNER_RESULTS_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(f'{exc.json_path}: {exc.message}') from exc

    unknown_keys = set(results.get('annotations', {})) - set(results['matchedRules'])
    if unknown_keys:
        raise ValueError(f'Annotation keys not in matchedRules: {sorted(unknown_keys)}')


def default_from_schema(schema):
    """Return a dict with default values filled in from a JSON schema.

    Only supports the flat objects."""
    obj = {}
    if not schema or not isinstance(schema, dict) or schema.get('type') != 'object':
        return obj
    for key in schema.get('keys', []):
        if 'default' in schema['keys'][key]:
            obj[key] = schema['keys'][key]['default']
    return obj
