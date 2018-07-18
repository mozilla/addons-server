from olympia.addons.models import AddonCategory, AddonUser
from olympia.amo.utils import slugify
from olympia.users.models import UserProfile


def generate_addon_user_and_category(addon, user, category):
    """
    Generate the dedicated `AddonUser` and `AddonCategory` for the given
    `addon` and `user`.

    """
    AddonUser.objects.create(addon=addon, user=user)
    AddonCategory.objects.create(addon=addon, category=category, feature=True)


def generate_user(email):
    """Generate a UserProfile given the `email` provided."""
    username = slugify(email)
    user, _ = UserProfile.objects.get_or_create(
        email=email, defaults={'username': username}
    )
    return user
