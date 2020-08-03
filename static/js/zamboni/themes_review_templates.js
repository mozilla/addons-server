/* This is an underscore.js template. It's pre-compiled so we don't need to
 * compile it on each page view, and also to avoid using the _.template()
 * helper which needs eval, which we want to prevent using CSP.
 *
 * If you need to change it, change the html/template in the comment below,
 * then copy the full _.template(...) call, and run it. The result will be a
 * function resembling the one below, uncommented, and this is the new
 * pre-compiled template you want to paste below. */

/*
_.template(`
  <table id="search-queue" class="data-grid items">
    <thead>
      <tr class="listing-header">
        <th>{{ gettext('Theme') }}</th>
        <th>{{ gettext('Reviewer') }}</th>
        <th>{{ gettext('Status') }}</th>
      </tr>
    </thead>
    <tbody><%= rows %></tbody>
  </table>
`).source;
*/

/* The following is the above commented template, pre-compiled. */

function search_results_template(obj) {
  var __t,
    __p = '',
    __j = Array.prototype.join,
    print = function () {
      __p += __j.call(arguments, '');
    };
  with (obj || {}) {
    __p +=
      '\n  <table id="search-queue" class="data-grid items">\n    <thead>\n      <tr class="listing-header">\n        <th>' +
      ((__t = gettext('Theme')) == null ? '' : _.escape(__t)) +
      '</th>\n        <th>' +
      ((__t = gettext('Reviewer')) == null ? '' : _.escape(__t)) +
      '</th>\n        <th>' +
      ((__t = gettext('Status')) == null ? '' : _.escape(__t)) +
      '</th>\n      </tr>\n    </thead>\n    <tbody>' +
      ((__t = rows) == null ? '' : __t) +
      '</tbody>\n  </table>\n';
  }
  return __p;
}

/*
_.template(`
  <tr class="addon-row">
    <td class="app-name">
      <span class="addon-id"><%= id %></span>
      <a href="<%= review_url %>"><%- name %></a>
    </td>
    <td>
      <% if (typeof reviewer !== "undefined") { %>
        <%- reviewer %>
      <% } %>
    </td>
    <td><%= status %></td>
  </tr>
`).source;
*/

/* The following is the above commented template, pre-compiled. */
function search_result_row_template(obj) {
  var __t,
    __p = '',
    __j = Array.prototype.join,
    print = function () {
      __p += __j.call(arguments, '');
    };
  with (obj || {}) {
    __p +=
      '\n <tr class="addon-row">\n   <td class="app-name">\n     <span class="addon-id">' +
      ((__t = id) == null ? '' : __t) +
      '</span>\n     <a href="' +
      ((__t = review_url) == null ? '' : __t) +
      '">' +
      ((__t = name) == null ? '' : _.escape(__t)) +
      '</a>\n   </td>\n   <td>\n     ';
    if (typeof reviewer !== 'undefined') {
      __p +=
        '\n       ' +
        ((__t = reviewer) == null ? '' : _.escape(__t)) +
        '\n     ';
    }
    __p +=
      '\n   </td>\n   <td>' +
      ((__t = status) == null ? '' : __t) +
      '</td>\n </tr>';
  }
  return __p;
}
