SET @GROUPS_TO_REMOVE = "Developers,Developers Credits,Engagement,Monolith API,OAuth Partner: Flightdeck,Other Contributors Credits,Past Developers Credits,Persona Reviewer MOTD,QA,Revenue Stats Viewers,System Administrators";

DELETE FROM groups_users WHERE group_id IN (SELECT id FROM groups WHERE FIND_IN_SET(name, @GROUPS_TO_REMOVE));
DELETE FROM groups WHERE FIND_IN_SET(name, @GROUPS_TO_REMOVE);
