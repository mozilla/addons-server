-- This file is run from cron before the database dump each day.  This resets a
-- couple core things that random people might change on the site.

REPLACE INTO config (`key`,`value`) 
VALUES (
    "site_notice",
    "This is a public test server.  <b>Any information on this site is public including passwords.  Don't put private information here!</b>  For more information:  <a href=\"http://micropipes.com/blog/2011/03/29/welcome-to-the-landfill/\">What this server is for</a> or the <a href=\"http://jbalogh.github.com/zamboni/\">development documentation</a>");

-- password is "nobody"
UPDATE users SET 
    email="nobody@mozilla.org",
    username="landfilladmin",
    display_name="Landfill Admin",
    password="sha512$3cd0cddefc8711c73b9b7190e13e755bd1c00e9dcbf6d837956fa9dc92dab2e1$5669268c0f604520f13b5b956580bf137914df81f99702b77d462ac24f7b63e60611560ee754ad729674149543d11e54d7596453d9a739c40a0a5a4ca4b062e1",
    homepage="https://landfill.addons.allizom.org"
WHERE id=1;
