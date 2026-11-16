import { css } from 'lit';

// acorn's rows keep the arrow cursor of the Firefox menus its panel-list is
// ported from, but on the web a row that navigates reads as clickable. Drop
// this once a release carries the same change upstream.
export const panelPointer = css`
  moz-panel-item::part(button),
  moz-panel-item::part(action) {
    cursor: pointer;
  }
  moz-panel-item[disabled]::part(button) {
    cursor: not-allowed;
  }
`;
