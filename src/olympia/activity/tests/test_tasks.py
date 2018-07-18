import mock
import pytest

from olympia.activity.models import ActivityLogEmails
from olympia.activity.tasks import process_email
from olympia.activity.tests.test_utils import sample_message_content


@pytest.mark.django_db
@mock.patch('olympia.activity.tasks.add_email_to_activity_log_wrapper')
def test_process_email(_mock):
    # MessageId not in the message we pass to process_email should fail too.
    process_email({})
    assert _mock.call_count == 0
    message = sample_message_content.get('Message')
    process_email(message)
    assert _mock.call_count == 1
    assert ActivityLogEmails.objects.filter(
        messageid='This is a MessageID'
    ).exists()
    # don't try to process the same message twice
    process_email(message)
    assert _mock.call_count == 1
    assert ActivityLogEmails.objects.count() == 1


@pytest.mark.django_db
@mock.patch('olympia.activity.tasks.add_email_to_activity_log_wrapper')
def test_process_email_different_messageid(_mock):
    # Test 'Message-ID' works too.
    message = {
        'CustomHeaders': [{'Name': 'Message-ID', 'Value': '<gmail_tastic>'}]
    }
    process_email(message)
    assert ActivityLogEmails.objects.filter(
        messageid='<gmail_tastic>'
    ).exists()
    assert _mock.call_count == 1
    # don't try to process the same message twice
    process_email(message)
    assert _mock.call_count == 1
    assert ActivityLogEmails.objects.count() == 1


@pytest.mark.django_db
@mock.patch('olympia.activity.tasks.add_email_to_activity_log_wrapper')
def test_process_email_different_messageid_case(_mock):
    # Test 'Message-Id' (different case)
    message = {'CustomHeaders': [{'Name': 'Message-Id', 'Value': '<its_ios>'}]}
    process_email(message)
    assert ActivityLogEmails.objects.filter(messageid='<its_ios>').exists()
    assert _mock.call_count == 1
    # don't try to process the same message twice
    process_email(message)
    assert _mock.call_count == 1
    assert ActivityLogEmails.objects.count() == 1
