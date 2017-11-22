import json
import os
from base64 import urlsafe_b64encode
from datetime import datetime
from urllib import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.utils.http import is_safe_url

import boto3

from olympia.core.logger import getLogger
from olympia.accounts.tasks import primary_email_change_event


def fxa_config(request):
    config = {camel_case(key): value
              for key, value in settings.FXA_CONFIG['default'].iteritems()
              if key != 'client_secret'}
    if request.user.is_authenticated():
        config['email'] = request.user.email
    request.session.setdefault('fxa_state', generate_fxa_state())
    config['state'] = request.session['fxa_state']
    return config


def fxa_login_url(config, state, next_path=None, action=None):
    if next_path and is_safe_url(next_path):
        state += ':' + urlsafe_b64encode(next_path.encode('utf-8')).rstrip('=')
    query = {
        'client_id': config['client_id'],
        'redirect_url': config['redirect_url'],
        'scope': config['scope'],
        'state': state,
    }
    if action is not None:
        query['action'] = action
    return '{host}/authorization?{query}'.format(
        host=config['oauth_host'], query=urlencode(query))


def default_fxa_register_url(request):
    request.session.setdefault('fxa_state', generate_fxa_state())
    return fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path_with_query(request),
        action='signup')


def default_fxa_login_url(request):
    request.session.setdefault('fxa_state', generate_fxa_state())
    return fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=request.session['fxa_state'],
        next_path=path_with_query(request),
        action='signin')


def generate_fxa_state():
    return os.urandom(32).encode('hex')


def redirect_for_login(request):
    return HttpResponseRedirect(default_fxa_login_url(request))


def path_with_query(request):
    next_path = request.path
    qs = request.GET.urlencode()
    if qs:
        return u'{next_path}?{qs}'.format(next_path=next_path, qs=qs)
    else:
        return next_path


def camel_case(snake):
    parts = snake.split('_')
    return parts[0] + ''.join(part.capitalize() for part in parts[1:])


def process_fxa_event(raw_body, **kwargs):
    """Parse and process a single firefox account event."""
    # Try very hard not to error out if there's junk in the queue.
    log = getLogger('accounts.sqs')
    event_type = None
    try:
        body = json.loads(raw_body)
        event = json.loads(body['Message'])
        event_type = event.get('event')
        uid = event.get('uid')
        timestamp = datetime.fromtimestamp(event.get('ts', ''))
        if not (event_type and uid and timestamp):
            raise ValueError(
                'Properties event, uuid, and ts must all be non-empty')
    except (ValueError, KeyError, TypeError), e:
        log.exception('Invalid account message: %s' % e)
    else:
        if event_type == 'primaryEmailChanged':
            email = event.get('email')
            if not email:
                log.error('Email property must be non-empty for "%s" event' %
                          event_type)
            else:
                primary_email_change_event.delay(email, uid, timestamp)
        else:
            log.debug('Dropping unknown event type %r', event_type)


def process_sqs_queue(queue_url, aws_region, queue_wait_time):
    log = getLogger('accounts.sqs')
    log.info('Processing account events from %s', queue_url)
    try:
        # Connect to the SQS queue.
        sqs = boto3.client(
            'sqs', aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=aws_region)
        # Poll for messages indefinitely.
        while True:
            response = sqs.receive_message(
                QueueUrl=queue_url, WaitTimeSeconds=queue_wait_time,
                MaxNumberOfMessages=10)
            msgs = response.get('Messages', []) if response else []
            for message in msgs:
                try:
                    process_fxa_event(message.get('Body', ''))
                    # This intentionally deletes the event even if it was some
                    # unrecognized type.  Not point leaving a backlog.
                    if 'ReceiptHandle' in message:
                        sqs.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=message['ReceiptHandle'])
                except Exception as exc:
                    log.exception('Error while processing message: %s' % exc)
    except Exception as exc:
        log.exception('Error while processing account events: %s' % exc)
        raise exc
