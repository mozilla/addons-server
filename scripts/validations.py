"""
Process validation data retrieved using fetch_validation_data.py. Two types
of data are expected. A file at `validations/unlisted-addons.txt` that contains
the guid of each unlisted addon and input on STDIN which has the validation
JSON data for each validation to check. See fetch_validation_data.py for how
this data is retrieved. Results are returned on STDOUT.

The following reports are supported:
    * count - Return signing errors ordered by addon unique frequency in the
        format: `error.id.dot.separated total_count unique_addon_count`.
    * context - Return the context for 5 most common signing errors in the JSON
        format: `{"context": ["", ...], "error": "error.id"}`.

Usage:
    cat my-test-data-*.txt | python validations.py <report> > results.txt
"""

import itertools
import json
import sys

ACTION_CONTEXT = 'context'
ACTION_COUNT = 'count'
ACTIONS = (ACTION_CONTEXT, ACTION_COUNT)


def parse_validations(results):
    return (json.loads(result) for result in results)


def unlisted_validations(results, unlisted_addons=None):
    if unlisted_addons is None:
        unlisted_addons = get_unlisted_addons()
    return (result
            for result in results
            if ('id' in result['metadata'] and
                (not result['metadata'].get('listed', True)
                 or result['metadata']['id'] in unlisted_addons)))


def severe_validations(results):
    return (result
            for result in results
            if (result['signing_summary']['high'] > 0 or
                result['signing_summary']['medium'] > 0 or
                result['signing_summary']['low'] > 0))


def error_messages(results):
    return ({'addon': result['metadata']['id'],
             'message_id': '.'.join(message['id']),
             'context': message['context']}
            for result in results
            for message in result['messages']
            if 'signing_severity' in message)


def sort_by_message(results):
    return sorted(results, key=lambda r: r['message_id'])


def group_by_message(results):
    return itertools.groupby(results, lambda r: r['message_id'])


def extract_error_results(results):
    for error, messages in results:
        all_messages = list(messages)
        yield {
            'error': error,
            'total': len(all_messages),
            'unique': len(set(msg['addon'] for msg in all_messages)),
            'contexts': [msg['context'] for msg in all_messages],
        }


def sort_results_by_unique(results):
    return sorted(results, reverse=True, key=lambda r: r['unique'])


def format_error_count(results):
    return ('{error} {total} {unique}'.format(**result)
            for result in results)


def format_contexts(results):
    for result in results:
        for context in result['contexts']:
            yield json.dumps({
                'error': result['error'],
                'context': context,
            })


def get_unlisted_addons():
    with open('validations/unlisted-addons.txt') as f:
        return set(guid.strip() for guid in f)


def main(action):
    pipeline = [
        parse_validations,
        unlisted_validations,
        severe_validations,
        error_messages,
        sort_by_message,
        group_by_message,
        extract_error_results,
        sort_results_by_unique,
    ]

    if action == ACTION_CONTEXT:
        # Only get context for the top 5 errors (they're already sorted by
        # unique occurrences so we can just take the first 5).
        pipeline.append(lambda results: itertools.islice(results, 5))
        pipeline.append(format_contexts)
    elif action == ACTION_COUNT:
        pipeline.append(format_error_count)
    else:
        raise ValueError('{0} is not a valid action'.format(action))

    process_pipeline(pipeline)


def process_pipeline(pipeline):
    # Read from STDIN.
    val = sys.stdin

    # Process through the pipeline.
    for fn in pipeline:
        val = fn(val)

    # Print the results.
    for line in val:
        print line

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        print """Usage: python {name} <action>
    action: {actions}
    values are read from STDIN""".format(
            name=sys.argv[0], actions='|'.join(ACTIONS))
        sys.exit(1)
    else:
        main(sys.argv[1])
