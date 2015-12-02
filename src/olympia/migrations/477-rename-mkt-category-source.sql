-- Any app on "Home" is always featured.
-- On category browse pages the top three apps with 16px icons are featured.
update download_sources set name = 'mkt-category-featured' where name = 'mkt-featured';

-- Add separate ones for /apps/.
insert into download_sources (name, type, created)
    values ('mkt-browse', 'full', NOW()),
           ('mkt-browse-featured', 'full', NOW());
