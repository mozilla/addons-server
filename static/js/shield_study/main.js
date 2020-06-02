
function trackEvent(event) {
  ga('send', 'event', 'opt-in', 'click'); // Will need to filter on utm_source
  event.target.innerHTML = "Thank you! Opted In";
  event.target.setAttribute("onclick","");
  return true; // For href to work
}


$(document).ready(function() {
  let optIn = document.getElementById("opt-in")
  optIn.onclick = trackEvent;
  optIn.oncontextmenu = function() {return false;}
});
