-- By deleting the orphaned profiles they will be able to re-register
-- with the same browser ID login. See bug 731776.

delete stats_contributions
    from stats_contributions
    join users on stats_contributions.user_id=users.id
    left join auth_user on auth_user.id=users.user_id
    where auth_user.id is null and users.created > '2012-02-28 00:00:00';

delete users_install
    from users_install
    join users on users_install.user_id=users.id
    left join auth_user on auth_user.id=users.user_id
    where auth_user.id is null and users.created > '2012-02-28 00:00:00';

delete users_preapproval
    from users_preapproval
    join users on users_preapproval.user_id=users.id
    left join auth_user on auth_user.id=users.user_id
    where auth_user.id is null and users.created > '2012-02-28 00:00:00';

delete users
    from users
    left join auth_user on auth_user.id=users.user_id
    where auth_user.id is null and users.created > '2012-02-28 00:00:00';
