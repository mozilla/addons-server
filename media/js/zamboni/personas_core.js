/**
 * Bubbles up persona event to tell Firefox to load a persona
 **/
function dispatchPersonaEvent(aType, aNode, callback)
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
        if (callback) {
            callback();
        }
    } catch(e) {}
}


$.hasPersonas = function() {
    if (!jQuery.browser.mozilla) return false;

    // Fx 3.6 has lightweight themes (aka personas)
    if (VersionCompare.compareVersions(
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
