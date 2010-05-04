$(document).ready(function() {
    var personas = $('.persona-preview');
    if (!personas.length) return;

    personas.previewPersona(true);
});

/**
 * Bubbles up persona event to tell Firefox to load a persona
 **/
function dispatchPersonaEvent(aType, aNode)
{
    var aliases = {'PreviewPersona': 'PreviewBrowserTheme',
                   'ResetPersona': 'ResetBrowserThemePreview',
                   'SelectPersona': 'InstallBrowserTheme'};
    try {
        if (!aNode.hasAttribute("data-browsertheme"))
			return;

        $(aNode).attr("persona", $(aNode).attr("data-browsertheme"));

        var aliasEvent = aliases[aType];
        var events = [aType, aliasEvent];

        for (var i=0; i<events.length; i++) {
          var event = events[i];
          var eventObject = document.createEvent("Events");
          eventObject.initEvent(event, true, false);
          aNode.dispatchEvent(eventObject);
        }
    } catch(e) {}
}

/**
 * Binds Personas preview events to the element.
 * Click - bubbles up ResetPersona event
 * Mouseenter - bubbles up PreviewPersona
 * Mouseleave - bubbles up ResetPersona
 **/
$.fn.previewPersona = function(resetOnClick) {
    if (resetOnClick) {
        $(this).click(function(e) {
            dispatchPersonaEvent('ResetPersona', e.originalTarget);
        });
    }

    $(this).hoverIntent({
        interval: 100,
        over: function(e) {
            $(this).closest('.persona').addClass('persona-hover');
            dispatchPersonaEvent('PreviewPersona', e.originalTarget);
        },
        out: function(e) {
            $(this).closest('.persona').removeClass('persona-hover');
            dispatchPersonaEvent('ResetPersona', e.originalTarget);
        }
    });
};


/* Should be called on an anchor. */
$.fn.personasButton = function(options) {
    var persona_wrapper = $(this).closest('.persona');
    persona_wrapper.hoverIntent({
        interval: 100,
        over: function(e) {
            dispatchPersonaEvent('PreviewPersona', e.currentTarget);
        },
        out: function(e) {
            dispatchPersonaEvent('ResetPersona', e.currentTarget);
        }
    });
    persona_wrapper.click(function(e) {
        dispatchPersonaEvent('SelectPersona', e.currentTarget);
        return false;
    });
};


$.hasPersonas = function() {
    if (!jQuery.browser.mozilla) return false;

    // Fx 3.6 has lightweight themes (aka personas)
    var versionCompare = new VersionCompare();
    if (versionCompare.compareVersions(
        $.browser.version, '1.9.2') > -1) {
        return true;
    }

    var body = document.getElementsByTagName("body")[0];
    try {
        var event = document.createEvent("Events");
        event.initEvent("CheckPersonas", true, false);
        body.dispatchEvent(event);
    } catch(e) {}

    return body.getAttribute("personas") == "true";
};
