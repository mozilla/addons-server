/* prevent-default function wrapper */
export function _pd(func) {
  return function (e) {
    e.preventDefault();
    func.apply(this, arguments);
  };
}
