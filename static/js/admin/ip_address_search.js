import { Netmask } from 'netmask';

document.addEventListener('DOMContentLoaded', () => {
  /* Those variables are used in the functions below, and initialized a bit
     later if we're on a userprofile changelist page */
  const search_bar = document.querySelector('#searchbar');

  function get_search_bar_terms() {
    /**
     * Return a Set of all search terms in the search bar.
     */
    if (!search_bar) {
      return new Set();
    }

    const search_term = search_bar.value.trim();
    return new Set(
      search_term
        ? search_term.split(',').map(function (x) {
            return x.trim();
          })
        : [],
    );
  }

  const original_search_terms = get_search_bar_terms();
  const ip_fields = document.querySelectorAll(
    '.change-list .field-known_ip_adresses li',
  );

  function are_set_equal(a, b) {
    /** Return whether or not two sets contains the same values. */
    if (a.size !== b.size) {
      return false;
    }
    for (const value of a) {
      if (!b.has(value)) {
        return false;
      }
    }
    return true;
  }

  function highlight_ips_not_in(values) {
    /**
     * Highlight fields containing an IP not already in Set passed as argument
     * by setting a 'notinsearch' class. Also reset it on existing fields if
     * it was present but is no longer accurate, and apply the 'dirty' class
     * to the search bar if the value is different from when the page was
     * loaded.
     */
    for (const field of ip_fields) {
      const ip = field.textContent;
      if (ip.length <= 1) {
        continue;
      }
      // Our Set can contain IPs and networks, so we can't just do
      // values.has(ip), we have to iterate on it and look if it's contained
      // in the corresponding block (Netmask(ip) returns a block with only that
      // IP in it).
      let found = false;
      values.forEach((item) => {
        let block = new Netmask(item);
        if (block.contains(ip)) {
          found = true;
          return;
        }
      });

      if (!found) {
        field.classList.add('notinsearch');
      } else {
        field.classList.remove('notinsearch');
      }
    }

    if (!search_bar) {
      return;
    }

    if (!are_set_equal(original_search_terms, values)) {
      search_bar.classList.add('dirty');
    } else {
      search_bar.classList.remove('dirty');
    }
  }

  function add_add_remove_links() {
    /**
     * Add hidden links next to every IP field to add or remove the value to
     * the search terms.
     * They will be shown when hovering elements with the 'hasadremovedip'
     * class, so add that class to each parent as well.
     */
    for (const field of ip_fields) {
      const value = field.textContent;
      if (value.length <= 1) {
        continue;
      }
      const add_link = document.createElement('a');
      add_link.className = 'addlink';
      field.appendChild(add_link);

      const delete_link = document.createElement('a');
      delete_link.className = 'deletelink';
      field.appendChild(delete_link);

      field.classList.add('hasaddremoveip');
    }
  }

  const result_list = document.querySelector('body.change-list #result_list');

  if (!result_list) {
    return;
  }

  add_add_remove_links();
  const values = get_search_bar_terms();
  if (search_bar) {
    search_bar.value = [...values].join(', ');
  }
  highlight_ips_not_in(values);

  document.querySelector('#result_list').addEventListener('click', (e) => {
    const target = e.target;
    const field = target.parentElement;

    if (field.classList.contains('hasaddremoveip')) {
      const new_value = field.textContent.trim();
      const values = get_search_bar_terms();
      if (target.classList.contains('addlink')) {
        values.add(new_value);
      } else if (target.classList.contains('deletelink')) {
        values.delete(new_value);
      }
      if (search_bar) {
        search_bar.value = [...values].join(', ');
      }
      highlight_ips_not_in(values);
    }
  });
});
