import mock

from olympia.activity.tasks import process_email
from olympia.activity.tests.test_utils import sample_message_content


@mock.patch('olympia.activity.tasks.add_email_to_activity_log_wrapper')
def test_process_email(_mock):
    # MessageId not in the message we pass to process_email should fail too.
    process_email({})
    assert _mock.call_count == 0
    message = sample_message_content.get('Message')
    process_email(message)
    assert _mock.call_count == 1
    # don't try to process the same message twice
    process_email(message)
    assert _mock.call_count == 1


@mock.patch('olympia.activity.tasks.add_email_to_activity_log_wrapper')
def test_process_email_different_messageid(_mock):
    # Test 'Message-ID' works too.
    message = {'CustomHeaders': [
        {'Name': 'Message-ID', 'Value': '<gmail_tastic>'}]}
    process_email(message)
    assert _mock.call_count == 1
    # don't try to process the same message twice
    process_email(message)
    assert _mock.call_count == 1
