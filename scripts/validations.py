import itertools
import json
import sys

ACTION_CONTEXT = 'context'
ACTION_COUNT = 'count'
ACTIONS = (ACTION_CONTEXT, ACTION_COUNT)

with open('validations/unlisted-addons.txt') as f:
    UNLISTED_ADDONS = set(guid.strip() for guid in f)


def parse_validations(results):
    return (json.loads(result) for result in results)


def unlisted_validations(results):
    return (result
            for result in results
            if (not result['metadata'].get('listed', True)
                or result['metadata'].get('id') in UNLISTED_ADDONS))


def severe_validations(results):
    return (result
            for result in results
            if any(err > 0 for err in result['signing_summary']))


def error_messages(results):
    return ({'addon': result['metadata'].get('id', 'unknown-addon'),
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
        pipeline.append(lambda results: itertools.islice(results, 5))
        pipeline.append(format_contexts)
    elif action == ACTION_COUNT:
        pipeline.append(format_error_count)
    else:
        raise ValueError('{0} is not a valid action'.format(action))

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
        print '''Usage: python {name} <action>
    action: {actions}
    values are read from STDIN'''.format(
            name=sys.argv[0], actions=', '.join(ACTIONS))
        sys.exit(1)
    else:
        main(sys.argv[1])
