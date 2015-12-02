-- Once upon a time, Zamboni didn't create user accounts in a
-- transaction. Sometimes an `auth_user` row would get created and a
-- `users` row would not. Since this leaves the owner of this email
-- unable to login or re-register, we delete them.

delete auth_user from auth_user left join users on auth_user.id = users.id where users.id is null;
