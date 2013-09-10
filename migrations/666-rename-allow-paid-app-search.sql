UPDATE waffle_flag_mkt set name = 'override-app-purchase', note = 'ON: allow app purchase to specific people when the setting PURCHASE_LIMITED is True' where name = 'allow-paid-app-search';
