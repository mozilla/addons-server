from django.conf import settings

from tower import ugettext as _

from amo.utils import escape_all


def make_validation_results(data, is_compatibility=False):
    if data['validation']:
        data['validation'] = limit_validation_results(escape_validation(
            data['validation']))
    data['error'] = hide_traceback(data['error'])
    return data


def hide_traceback(error):
    """Safe wrapper around JSON dict containing a validation result.
    """
    if not settings.EXPOSE_VALIDATOR_TRACEBACKS and error:
        # Just expose the message, not the traceback
        return error.strip().split('\n')[-1].strip()
    else:
        return error


def limit_validation_results(validation, is_compatibility=False):
    lim = settings.VALIDATOR_MESSAGE_LIMIT
    if lim:
        del validation['messages'][lim:]
        if validation.get('compatibility_summary'):
            cs = validation['compatibility_summary']
            compatibility_count = (
                cs['errors'] + cs['warnings'] + cs['notices'])
        else:
            cs = {}
            compatibility_count = 0
        leftover_count = (validation.get('errors', 0)
                          + validation.get('warnings', 0)
                          + validation.get('notices', 0)
                          + compatibility_count
                          - lim)
        if leftover_count > 0:
            msgtype = 'notice'
            if is_compatibility:
                if cs.get('errors'):
                    msgtype = 'error'
                elif cs.get('warnings'):
                    msgtype = 'warning'
            else:
                if validation['errors']:
                    msgtype = 'error'
                elif validation['warnings']:
                    msgtype = 'warning'
            validation['messages'].append({
                'tier': 1,
                'type': msgtype,
                'message': (_('Validation generated too many errors/'
                              'warnings so %s messages were truncated. '
                              'After addressing the visible messages, '
                              "you'll be able to see the others.")
                            % (leftover_count,)),
                'compatibility_type': None,
                })
    if is_compatibility:
        compat = validation['compatibility_summary']
        for k in ('errors', 'warnings', 'notices'):
            validation[k] = compat[k]
        for msg in validation['messages']:
            if msg['compatibility_type']:
                msg['type'] = msg['compatibility_type']
    return validation


def escape_validation(validation):
    ending_tier = validation.get('ending_tier', 0)
    for msg in validation.get('messages', []):
        tier = msg.get('tier', -1)  # Use -1 so we know it isn't 0.
        if tier > ending_tier:
            ending_tier = tier
        if tier == 0:
            # We can't display a message if it's on tier 0.
            # Should get fixed soon in bug 617481
            msg['tier'] = 1
    validation['ending_tier'] = ending_tier
    return escape_all(validation)
