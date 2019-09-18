ALTER TABLE `blogposts`
    MODIFY `created` datetime(6) NOT NULL,
    MODIFY `modified` datetime(6) NOT NULL,
    MODIFY `title` varchar(255) NOT NULL,
    MODIFY `date_posted` date NOT NULL,
    MODIFY `permalink` varchar(255) NOT NULL;
