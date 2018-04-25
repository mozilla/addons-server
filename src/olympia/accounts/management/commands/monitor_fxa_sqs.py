from django.conf import settings
from django.core.management.base import BaseCommand

from olympia.accounts.utils import process_sqs_queue
from olympia.core import logger


class Command(BaseCommand):
    """Monitor and process the AWS SQS queue for Firefox Account events.
    This function polls the specified SQS queue for account-related events,
    processing each as it is found.  It polls indefinitely and does not return;
    to interrupt execution you'll need to e.g. SIGINT the process.
    """
    help = 'Monitor the AWS SQS queue for FxA events.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--queue',
            action='store',
            dest='queue_url',
            default=settings.FXA_SQS_AWS_QUEUE_URL,
            help='Monitor specified SQS queue, rather than default.')

    def handle(self, *args, **options):
        queue_url = options['queue_url']
        # Quieten boto - we don't need that much chatter in our logs
        logger.logging.getLogger('boto3').setLevel(logger.logging.WARNING)
        logger.logging.getLogger('botocore').setLevel(logger.logging.WARNING)
        process_sqs_queue(queue_url)
