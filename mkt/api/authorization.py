from tastypie.authorization import ReadOnlyAuthorization


class AnonymousReadOnlyAuthorization(ReadOnlyAuthorization):
    def is_authorized(self, request, object=None):
        """
        Only allow ``GET`` requests for anonymous users.
        """
        if request.user.is_anonymous():
            sup = super(AnonymousReadOnlyAuthorization, self)
            return sup.is_authorized(request, object)
        return True
