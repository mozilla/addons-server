from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.amo.utils import chunked
from olympia.blocklist.models import BlocklistSubmission
from olympia.blocklist.utils import save_guids_to_blocks, splitlines
from olympia.users.utils import get_task_user


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = ('Create Blocks for provided guids to add them to the v3 blocklist')

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument('--min_version')
        parser.add_argument('--max_version')
        parser.add_argument('--reason')
        parser.add_argument('--url'),
        parser.add_argument(
            '--guids-input',
            help='Path to file with one guid per line that should be blocked',
            required=True)

    def handle(self, *args, **options):
        with open(options.get('guids_input'), 'r') as guid_file:
            input_guids = guid_file.read()
        guids = splitlines(input_guids)

        block_args = {
            prop: options.get(prop)
            for prop in ('min_version', 'max_version', 'reason', 'url')
            if options.get(prop)
        }
        block_args['updated_by'] = get_task_user()
        block_args['include_in_legacy'] = False
        submission = BlocklistSubmission(**block_args)

        for guids_chunk in chunked(guids, 100):
            blocks = save_guids_to_blocks(
                guids_chunk, submission, fields_to_set=block_args.keys())
            print(
                f'Added/Updated {len(blocks)} blocks from {len(guids_chunk)} '
                'guids')
