$(window).bind('login', function() {
    $('#login').addClass('show');
}).on('click', '.button.browserid', function(e) {
    e.preventDefault();
    var $this = $(this);
    $this.addClass('loading-submit');
    $.when(z.login())
     .done(function() {
         $this.removeClass('loading-submit');
         window.location.reload();
     })
     .fail(function(err) {
         $this.removeClass('loading-submit');
         if (err.privs) {
             $('#login').addClass('show old');
         } else {
             alert(err.msg);
         }
     });
});
// Hijack the login form to send us to the right place
$("#login form").submit(function(e) {
    var $this = $(this),
        action = $this.attr('action') + format("?to={0}", window.location.pathname);
    $this.attr('action', action);
});
