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
    $window.on('click', '.install-button a.button', function(e) {
        e.preventDefault();
        var $el = $(this);

        // When everything is loaded, trigger a click on the button
        $window.on('buttons_loaded_click', function() {
            $el.trigger('click');
        });
    });
    $window.on('buttons_loaded', function() {
        // Trigger all the clicks
        $window.trigger('buttons_loaded_click');

        // Clean up after ourselves
        $window.off('buttons_loaded buttons_loaded_click');
        $window.off('click', '.install-button a.button');
    });
})();
