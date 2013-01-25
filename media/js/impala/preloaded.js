/**
 * The point of this file is to do something
 * with criticial elements (such as buttons)
 * while we wait for the actual JS to load.
 *
 * That being said, this page should be treated
 * as volatile. Don't depend on this file being
 * shown. Everything in here should
 * merely be a stop-gap until the actual JS
 * loads.
 *
 */

(function() {
    var $window = $(window);
    $window.delegate('.install-button a.button', 'click', function(e) {
        e.preventDefault();
        var $el = $(this);

        // When everything is loaded, trigger a click on the button
        $window.bind('buttons_loaded_click', function() {
            $el.trigger('click');
        });
    });
    $window.bind('buttons_loaded', function() {
        // Trigger all the clicks
        $window.trigger('buttons_loaded_click');

        // Clean up after ourselves
        $window.unbind('buttons_loaded buttons_loaded_click');
        $window.undelegate('.install-button a.button', 'click');
    });
})();
