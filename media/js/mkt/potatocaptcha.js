define('potatocaptcha', [], function() {
    if (z.anonymous) {
        // If you're a robot, you probably don't have JS enabled ... unless you're
        // running headless WebKit - in which case spam us with all your potatoes.
        $('input[name=sprout]').val('potato');
    }
});
