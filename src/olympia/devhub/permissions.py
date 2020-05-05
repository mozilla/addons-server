from rest_framework.permissions import BasePermission

from olympia.devhub.utils import UploadRestrictionChecker


class IsSubmissionAllowedFor(BasePermission):
    """
    Like is_submission_allowed_for_request, but in Permission form for use in
    the API. If the client is disallowed, a message property specifiying the
    reason is set on the permission instance to be returned to the client in
    the 403 response.
    """
    def has_permission(self, request, view):
        checker = UploadRestrictionChecker(request)
        if not checker.is_submission_allowed():
            self.message = checker.get_error_message()
            self.code = 'permission_denied_restriction'
            return False
        return True

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
