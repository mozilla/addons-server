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
    * automated_count - Return daily totals for automated reviews.

Usage:
    cat my-test-data-*.txt | python validations.py <report> > results.txt
"""

import csv
import functools
import itertools
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

LOG_ACTION_PRELIMINARY = 42
LOG_ACTION_REJECTED = 43


def parse_validations(results):
    """Load each item in `results` as JSON."""
    return (json.loads(result) for result in results)


def load_validations_by_dated_filename(filenames, load_file=None):
    """Load JSON validations and include the date from text files of the format
    YYYY-MM-DD.txt."""

    def date_from_filename(filename):
        basename = os.path.basename(filename)
        return datetime.strptime(basename, '%Y-%m-%d.txt').date()

    def load_with_date(filename):
        date = date_from_filename(filename)
        with open(filename) as f:
            for result in parse_validations(f):
                result['date'] = date
                yield result

    if load_file is None:
        load_file = load_with_date

    return (result
            for filename in filenames
            for result in load_file(filename.strip()))


def unlisted_validations(results, unlisted_addons=None):
    """Filter `results` to only include validations for unlisted addons."""
    if unlisted_addons is None:
        unlisted_addons = get_unlisted_addons()
    return (result
            for result in results
            if ('id' in result['metadata'] and
                (not result['metadata'].get('listed', True)
                 or result['metadata']['id'] in unlisted_addons)))


def severe_validations(results):
    """Filter `results` to only include validations with low or higher signing
    severity."""
    return (result
            for result in results
            if (result['signing_summary']['high'] > 0 or
                result['signing_summary']['medium'] > 0 or
                result['signing_summary']['low'] > 0))


def automated_validations(results, unlisted_addons=None, lite_addons=None):
    """Filter `results` to only include validations that could potentially be
    automatically signed (whether or not they passed)."""
    if unlisted_addons is None:
        unlisted_addons = get_unlisted_addons()
    if lite_addons is None:
        lite_addons = get_lite_addons()
    return (result
            for result in results
            if ('id' in result['metadata']
                and result['metadata']['id'] in unlisted_addons
                and result['metadata']['id'] in lite_addons))


def error_messages(results):
    """Format validations to include all signing severity errors."""
    return ({'addon': result['metadata']['id'],
             'message_id': '.'.join(message['id']),
             'context': message['context']}
            for result in results
            for message in result['messages']
            if 'signing_severity' in message)


def sort_by_message(results):
    """Sort `results` by the message_id of the error messages."""
    return sorted(results, key=lambda r: r['message_id'])


def group_by_message(results):
    """Group `results` by message_id."""
    return itertools.groupby(results, lambda r: r['message_id'])


def extract_error_results(results):
    """Aggregate some data about validation errors."""
    for error, messages in results:
        all_messages = list(messages)
        yield {
            'error': error,
            'total': len(all_messages),
            'unique': len(set(msg['addon'] for msg in all_messages)),
            'contexts': [msg['context'] for msg in all_messages],
        }


def sort_results_by_unique(results):
    """Sort validation errors but number of unique occurrences."""
    return sorted(results, reverse=True, key=lambda r: r['unique'])


def format_error_count(results):
    """Basic output format for error messages."""
    return ('{error} {total} {unique}'.format(**result)
            for result in results)


def format_contexts(results):
    """Limit error messages to just error and context."""
    for result in results:
        for context in result['contexts']:
            yield json.dumps({
                'error': result['error'],
                'context': context,
            })


def set_from_file(filename):
    """Create a set from a file containing line separated strings."""
    with open(filename) as f:
        return set(guid.strip() for guid in f)


def get_unlisted_addons():
    """Load the unlisted addons file as a set."""
    return set_from_file('validations/unlisted-addons.txt')


def get_lite_addons():
    """Load the lite addons file as a set."""
    return set_from_file('validations/lite-addons.txt')


def context_pipeline():
    """Pipeline for generating error context messages."""
    return [
        parse_validations,
        unlisted_validations,
        severe_validations,
        error_messages,
        sort_by_message,
        group_by_message,
        extract_error_results,
        sort_results_by_unique,
        # Only get context for the top 5 errors (they're already sorted by
        # unique occurrences so we can just take the first 5).
        lambda results: itertools.islice(results, 5),
        format_contexts,
    ]


def count_pipeline():
    """Pipeline for getting error counts."""
    return [
        parse_validations,
        unlisted_validations,
        severe_validations,
        error_messages,
        sort_by_message,
        group_by_message,
        extract_error_results,
        sort_results_by_unique,
        format_error_count,
    ]


def automated_count(results):
    """Total automated review pass/fail for each day."""
    by_date = defaultdict(lambda: {'passed': 0, 'failed': 0})
    for result in results:
        if result['passed_auto_validation']:
            by_date[result['date']]['passed'] += 1
        else:
            by_date[result['date']]['failed'] += 1
    return ({'date': day, 'passed': totals['passed'],
             'failed': totals['failed'],
             'total': totals['passed'] + totals['failed']}
            for day, totals in by_date.iteritems())


def manual_count(results):
    """Total manual review pass/fail for each day."""
    by_date = defaultdict(lambda: {'passed': 0, 'failed': 0})
    for result in results:
        day = datetime.strptime(result['created'], '%Y-%m-%dT%H:%M%S').date()
        if result['action'] == LOG_ACTION_PRELIMINARY:
            by_date[day]['passed'] += 1
        elif result['action'] == LOG_ACTION_REJECTED:
            by_date[day]['failed'] += 1
        else:
            raise ValueError('Unexpected action {action}'.format(**result))
    return ({'date': day, 'passed': totals['passed'],
             'failed': totals['failed'],
             'total': totals['passed'] + totals['failed']}
            for day, totals in by_date.iteritems())


def print_tsv(results):
    """Format `results` as tab separated values to STDOUT."""
    writer = None
    for row in results:
        if writer is None:
            writer = csv.DictWriter(sys.stdout, fieldnames=row.keys(),
                                    dialect='excel-tab')
            writer.writeheader()
        writer.writerow(row)

sort_by_date = functools.partial(sorted, key=lambda count: count['date'])


def automated_count_pipeline(unlisted_addons=None, lite_addons=None,
                             load_file=None):
    """Pipeline for generating daily pass/fail for automated reviews."""
    return [
        functools.partial(load_validations_by_dated_filename,
                          load_file=load_file),
        functools.partial(automated_validations,
                          unlisted_addons=unlisted_addons,
                          lite_addons=lite_addons),
        automated_count,
        sort_by_date,
    ]


def manual_count_pipeline():
    """Pipeline for generating daily pass/fail for manual reviews."""
    return [
        parse_validations,
        manual_count,
        sort_by_date,
    ]


def reduce_pipeline(pipeline, iterable):
    """Run through a pipeline."""
    val = iterable

    # Process through the pipeline.
    for fn in pipeline:
        val = fn(val)

    return val


def print_results(results):
    """Print the results of a pipeline."""
    if hasattr(results, '__iter__'):
        for line in results:
            print line
    else:
        print results

ACTIONS = {
    'context': context_pipeline,
    'count': count_pipeline,
    'automated_count': automated_count_pipeline,
    'manual_count': manual_count_pipeline,
}

FORMATTERS = {
    'print': print_results,
    'tsv': print_tsv,
}


def main(action):
    """Run the specified pipeline."""
    format = os.environ.get('FORMAT', 'print')
    if action not in ACTIONS:
        raise ValueError('{0} is not a valid action'.format(action))
    elif format not in FORMATTERS:
        raise ValueError('{0} is not a valid formatter'.format(format))
    else:
        FORMATTERS[format](reduce_pipeline(ACTIONS[action](), sys.stdin))

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ACTIONS:
        print """Usage: python {name} <action>
    action: {actions}
    values are read from STDIN""".format(
            name=sys.argv[0], actions='|'.join(ACTIONS))
        sys.exit(1)
    else:
        main(sys.argv[1])
