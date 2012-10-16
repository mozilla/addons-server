$(window).bind('login', function() {
    $('#login').addClass('show');
}).on('click', '.browserid', function(e) {
    e.preventDefault();
    var $this = $(this),
        href = $this.attr('href'),
        qs = z.getVars(href.substring(href.indexOf('?')));
    $this.addClass('loading-submit');
    $.when(z.login(qs.to))
     .done(function() {
         $this.removeClass('loading-submit');
     })
     .fail(function(err) {
         $this.removeClass('loading-submit');
         if (err.privs) {
             $.post('/csrf', function(r) {
                $('#login form').append($('<input>',
                                        {type:'hidden', value:r.csrf,
                                         name:'csrfmiddlewaretoken'}));
             });
             $('#login').addClass('show old');
         } else {
             alert(err.msg);
         }
     });
});
// Hijack the login form to send us to the right place
$("#login form").submit(function(e) {
    e.stopPropagation();
    var $this = $(this),
        action = $this.attr('action') + format("?to={0}", window.location.pathname);
    $this.attr('action', action);
});
