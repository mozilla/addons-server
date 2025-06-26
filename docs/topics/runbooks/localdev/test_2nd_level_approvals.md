# Test 2nd level approvals

Test the reviewer tools 2nd level approval queue - "Held Decisions for 2nd Level Approval"


## Steps

### Make an add-on promoted

In the [django admin promoted](http://olympia.test/admin/models/discovery/discoveryaddon/) page, select an add-on.

If the `Promoted addons` section is empty, click `Add another Promoted addon`, then any group and any application from the select fields.  Then click the `Save and continue editing` button at the end of the page.  If the table already has at least one promotion you can skip adding a group.

In the table of properties click the `addon` link to navigate to the admin page for the add-on.

### Make the current version of the add-on signed

Go to the `Files` section (at the bottom) and open the change page for the most recent file version in a new tab.  (small `Change` link, alongside the instance pk number)

In the table of properties change `Status` to Approved if not already. If `Hash` and `Original Hash` fields are empty, enter some text in them (anything). In the Flags section check the `is signed` checkbox and Save the form.

Close the tab and return to the tab for the admin page for the add-on.  At the top of the page click the button for `Reviewer Tools (Listed)` to navigate to the review page for the add-on.

### Reject all Approved versions of the add-on

In the review page for the add-on, choose the "Reject Multiple Versions" action, and select all Approved-status versions in the list selection.  Choose any reason/policy from the list on the right hand side; enter any comments; and submit the form with the `Save` button.  The form should submit without any errors.

### Verify the add-on is in the 2nd level approval queue

Navigate to the [queue](http://olympia.test/reviewers/queue/held_decisions) - the decision on the add-on should be shown in the queue.
