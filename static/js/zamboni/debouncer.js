// debounce
// args:
//   function
//   milliseconds
//   context

function debounce(fn, ms, ctxt) {
  var ctx = ctxt || window;
  var to,
    del = ms,
    fun = fn;
  return function () {
    var args = arguments;
    clearTimeout(to);
    to = setTimeout(function () {
      fun.apply(ctx, args);
    }, del);
  };
}
