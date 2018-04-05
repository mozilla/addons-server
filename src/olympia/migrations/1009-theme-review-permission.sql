UPDATE groups SET rules=CONCAT(rules, ",Addons:ReviewTheme") WHERE name in ("Staff", "Reviewers: Themes");
