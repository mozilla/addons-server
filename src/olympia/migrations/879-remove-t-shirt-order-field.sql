ALTER table `users` 
    DROP column `t_shirt_requested`;

    DELETE FROM waffle_switch 
    WHERE name = 't-shirt-orders';
