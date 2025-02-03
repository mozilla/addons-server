/* Python(ish) string formatting:
 * >>> format('{0}', ['zzz'])
 * "zzz"
 * >>> format('{0}{1}', 1, 2)
 * "12"
 * >>> format('{x}', {x: 1})
 * "1"
 */
export function format(s, args) {
  let re = /\{([^}]+)\}/g;
  if (!s) {
    throw 'Format string is empty!';
  }
  if (!args) return;
  if (!(args instanceof Array || args instanceof Object))
    args = Array.prototype.slice.call(arguments, 1);
  return s.replace(re, function (_, match) {
    return args[match];
  });
}

export function template(s) {
  if (!s) {
    throw 'Template string is empty!';
  }
  return function (args) {
    return format(s, args);
  };
}
