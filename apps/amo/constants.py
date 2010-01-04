# Add-on and File statuses.
STATUS_NULL = 0
STATUS_SANDBOX = 1
STATUS_PENDING = 2
STATUS_NOMINATED = 3
STATUS_PUBLIC = 4
STATUS_DISABLED = 5
STATUS_LISTED = 6
STATUS_BETA = 7

STATUS_CHOICES = {
    STATUS_NULL: 'Null',
    STATUS_SANDBOX: 'In the sandbox',
    STATUS_PENDING: 'Pending approval',
    STATUS_NOMINATED: 'Nominated to be public',
    STATUS_PUBLIC: 'Public',
    STATUS_DISABLED: 'Disabled',
    STATUS_LISTED: 'Listed',
    STATUS_BETA: 'Beta',
}
