// Ported from olympia.amo.templatetags.jinja_helpers.PaginationRenderer so the
// new pager shows the same page numbers as the one it replaces.

export interface PaginationRange {
  pages: number[];
  /** Page 1 is outside the window, so it's pinned behind a leading ellipsis. */
  dottedLower: boolean;
  /** Likewise the last page, behind a trailing ellipsis. */
  dottedUpper: boolean;
}

export function paginationRange(
  page: number,
  numPages: number,
  maxSlots: number,
): PaginationRange {
  const span = Math.floor((maxSlots - 1) / 2);
  let lower: number;
  let upper: number;
  if (numPages < maxSlots) {
    [lower, upper] = [0, numPages];
  } else if (page < span + 1) {
    [lower, upper] = [0, span * 2];
  } else if (page > numPages - span) {
    [lower, upper] = [numPages - span * 2, numPages];
  } else {
    [lower, upper] = [page - span, page + span - 1];
  }

  const from = Math.max(lower + 1, 1);
  const to = Math.min(numPages, upper);
  const pages: number[] = [];
  for (let n = from; n <= to; n++) pages.push(n);

  return {
    pages,
    dottedLower: !pages.includes(1),
    dottedUpper: !pages.includes(numPages),
  };
}
