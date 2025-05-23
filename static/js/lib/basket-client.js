/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

(function () {
  // !! this file assumes only one signup form per page !!

  let newsletterForm = document.getElementById('newsletter_form');
  let newsletterWrapper = document.getElementById('newsletter_wrap');

  // handle errors
  let errorArray = [];
  let newsletterErrors = document.getElementById('newsletter_errors');
  function newsletterError(e) {
    let errorList = document.createElement('ul');

    if (errorArray.length) {
      for (let i = 0; i < errorArray.length; i++) {
        let item = document.createElement('li');
        item.appendChild(document.createTextNode(errorArray[i]));
        errorList.appendChild(item);
      }
    } else {
      // no error messages, forward to server for better troubleshooting
      newsletterForm.setAttribute('data-skip-xhr', true);
      newsletterForm.submit();
    }

    newsletterErrors.appendChild(errorList);
    newsletterErrors.style.display = 'block';
  }

  // show sucess message
  function newsletterThanks() {
    let thanks = document.getElementById('newsletter_thanks');

    // show thanks message
    thanks.style.display = 'block';
  }

  // XHR subscribe; handle errors; display thanks message on success.
  function newsletterSubscribe(evt) {
    let skipXHR = newsletterForm.getAttribute('data-skip-xhr');
    if (skipXHR) {
      return true;
    }
    evt.preventDefault();
    evt.stopPropagation();

    // new submission, clear old errors
    errorArray = [];
    newsletterErrors.style.display = 'none';
    while (newsletterErrors.firstChild) {
      newsletterErrors.removeChild(newsletterErrors.firstChild);
    }

    let fmt = document.getElementById('fmt').value;
    let email = document.getElementById('email').value;
    let newsletter = document.getElementById('newsletters').value;
    let privacy = document.querySelector('input[name="privacy"]:checked')
      ? '&privacy=true'
      : '';
    let params =
      'email=' +
      encodeURIComponent(email) +
      '&newsletters=' +
      newsletter +
      privacy +
      '&fmt=' +
      fmt +
      '&source_url=' +
      encodeURIComponent(document.location.href);

    let xhr = new XMLHttpRequest();

    xhr.onload = function (r) {
      if (r.target.status >= 200 && r.target.status < 300) {
        // response is null if handled by service worker
        if (response === null) {
          newsletterError(new Error());
          return;
        }
        let response = r.target.response;
        if (response.success === true) {
          newsletterForm.style.display = 'none';
          newsletterThanks();
        } else {
          if (response.errors) {
            for (let i = 0; i < response.errors.length; i++) {
              errorArray.push(response.errors[i]);
            }
          }
          newsletterError(new Error());
        }
      } else {
        newsletterError(new Error());
      }
    };

    xhr.onerror = function (e) {
      newsletterError(e);
    };

    let url = newsletterForm.getAttribute('action');

    xhr.open('POST', url, true);
    xhr.setRequestHeader('Content-type', 'application/x-www-form-urlencoded');
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.timeout = 5000;
    xhr.ontimeout = newsletterError;
    xhr.responseType = 'json';
    xhr.send(params);

    return false;
  }

  newsletterForm.addEventListener('submit', newsletterSubscribe, false);
})();
