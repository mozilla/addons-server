import string

from users.models import UserProfile


allowed_chars = string.ascii_letters + string.digits
make_password = UserProfile.objects.make_random_password

for user in UserProfile.objects.filter(password=""):
    user.set_password(make_password(length=50, allowed_chars=allowed_chars))
    user.notes = 'bug1035375'
    user.save()
