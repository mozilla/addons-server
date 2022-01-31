import binascii
import json
import os

from base64 import urlsafe_b64encode
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.encoding import force_str

import boto3

from olympia.amo.utils import is_safe_url, use_fake_fxa
from olympia.core.logger import getLogger

from .tasks import clear_sessions_event, delete_user_event, primary_email_change_event


def fxa_login_url(
    config,
    state,
    next_path=None,
    action=None,
    force_two_factor=False,
    request=None,
    id_token=None,
):
    if next_path and is_safe_url(next_path, request):
        state += ':' + force_str(urlsafe_b64encode(next_path.encode('utf-8'))).rstrip(
            '='
        )
    query = {
        'client_id': config['client_id'],
        'scope': 'profile openid',
        'state': state,
        'access_type': 'offline',
    }
    if action is not None:
        query['action'] = action
    if force_two_factor is True:
        # Specifying AAL2 will require the token to have an authentication
        # assurance level >= 2 which corresponds to requiring 2FA.
        query['acr_values'] = 'AAL2'
        # Requesting 'prompt=none' during authorization, together with passing
        # a valid id token in 'id_token_hint', allows the user to not have to
        # re-authenticate with FxA if they still have a valid session (which
        # they should here: they went through FxA, back to AMO, and now we're
        # redirecting them to FxA because we want them to have 2FA enabled).
        if id_token:
            query['prompt'] = 'none'
            query['id_token_hint'] = id_token
    if use_fake_fxa():
        base_url = reverse('fake-fxa-authorization')
    else:
        base_url = f'{settings.FXA_OAUTH_HOST}/authorization'
    return f'{base_url}?{urlencode(query)}'


def generate_fxa_state():
    return force_str(binascii.hexlify(os.urandom(32)))


def redirect_for_login(request):
    request.session.setdefault('fxa_state', generate_fxa_state())
    url = fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path_with_query(request),
        action='signin',
    )
    return HttpResponseRedirect(url)


def path_with_query(request):
    next_path = request.path
    qs = request.GET.urlencode()
    if qs:
        return f'{next_path}?{qs}'
    else:
        return next_path


def camel_case(snake):
    parts = snake.split('_')
    return parts[0] + ''.join(part.capitalize() for part in parts[1:])


def process_fxa_event(raw_body):
    """Parse and process a single firefox account event."""
    # Try very hard not to error out if there's junk in the queue.
    log = getLogger('accounts.sqs')
    event_type = None
    try:
        body = json.loads(raw_body)
        event = json.loads(body['Message'])
        event_type = event.get('event')
        uid = event.get('uid')
        timestamp = event.get('ts', 0)
        if not (event_type and uid and timestamp):
            raise ValueError('Properties event, uuid, and ts must all be non-empty')
    except (ValueError, KeyError, TypeError) as e:
        log.exception('Invalid account message: %s' % e)
    else:
        if event_type == 'primaryEmailChanged':
            email = event.get('email')
            if not email:
                log.error(
                    'Email property must be non-empty for "%s" event' % event_type
                )
            else:
                primary_email_change_event.delay(uid, timestamp, email)
        elif event_type == 'delete':
            delete_user_event.delay(uid, timestamp)
        elif event_type in ['passwordChange', 'reset']:
            clear_sessions_event.delay(uid, timestamp, event_type)
        else:
            log.info('Dropping unknown event type %r', event_type)


def process_sqs_queue(queue_url):
    log = getLogger('accounts.sqs')
    log.info('Processing account events from %s', queue_url)
    try:
        region = queue_url.split('.')[1]
        available_regions = boto3._get_default_session().get_available_regions('sqs')
        if region not in available_regions:
            log.error(
                'SQS misconfigured, expected region, got %s from %s'
                % (region, queue_url)
            )
        # Connect to the SQS queue.
        # Credentials are specified in EC2 as an IAM role on prod/stage/dev.
        # If you're testing locally see boto3 docs for how to specify:
        # http://boto3.readthedocs.io/en/latest/guide/configuration.html
        sqs = boto3.client('sqs', region_name=region)
        # Poll for messages indefinitely.
        while True:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                WaitTimeSeconds=settings.FXA_SQS_AWS_WAIT_TIME,
                MaxNumberOfMessages=10,
            )
            msgs = response.get('Messages', []) if response else []
            for message in msgs:
                try:
                    process_fxa_event(message.get('Body', ''))
                    # This intentionally deletes the event even if it was some
                    # unrecognized type.  Not point leaving a backlog.
                    if 'ReceiptHandle' in message:
                        sqs.delete_message(
                            QueueUrl=queue_url, ReceiptHandle=message['ReceiptHandle']
                        )
                except Exception as exc:
                    log.exception('Error while processing message: %s' % exc)
    except Exception as exc:
        log.exception('Error while processing account events: %s' % exc)
        raise exc
