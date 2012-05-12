// CSRF Tokens
// Hijack the AJAX requests, and insert a CSRF token as a header.
$('html').ajaxSend(function(event, xhr, ajaxSettings) {
    var csrf, $meta;
    // Block anything that starts with 'http:', 'https:', '://' or '//'.
    if (!/^((https?:)|:?[/]{2})/.test(ajaxSettings.url)) {
        // Only send the token to relative URLs i.e. locally.
        $meta = $('meta[name=csrf]');
        if (!z.anonymous && $meta.length) {
            csrf = $meta.attr('content');
        } else {
            csrf = $("input[name='csrfmiddlewaretoken']").val();
        }
        if (csrf) {
            xhr.setRequestHeader('X-CSRFToken', csrf);
        }
    }
});