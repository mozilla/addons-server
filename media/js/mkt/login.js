$(window).bind('login', function() {
    $('#login').addClass('show');
});
$(window).on('click', '.button.browserid', function() {
    $.when(z.login())
     .done(function() {
        window.location.reload();
     })
     .fail(function(err) {
        if (err.privs) {
            $('#login').addClass('show old');
        } else {
            alert(err);
        }
     });
});
// Hijack the login form to send us to the right place
$("#login form").submit(function(e) {
    var action = $(this).attr('action') + format("?to={0}", window.location.pathname);
    $(this).attr('action', action);
});