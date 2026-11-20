import { openTargetedFaqItem } from "../../../static/js/zamboni/support_faq";

describe(__filename, () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    document.body.innerHTML = `
      <details class="faq-item" id="api-key-rate-limit">
        <summary>Question</summary>
        <div class="faq-answer">Answer</div>
      </details>
      <section id="contact"></section>
    `;
  });

  afterEach(() => {
    window.location.hash = "";
  });

  it("opens the FAQ entry matching the hash", () => {
    window.location.hash = "#api-key-rate-limit";
    openTargetedFaqItem();
    const item = document.getElementById("api-key-rate-limit");
    expect(item.open).toBe(true);
    expect(item.scrollIntoView).toHaveBeenCalled();
  });

  it("does nothing without a hash", () => {
    openTargetedFaqItem();
    expect(document.getElementById("api-key-rate-limit").open).toBe(false);
  });

  it("ignores hashes that do not point to a FAQ entry", () => {
    window.location.hash = "#contact";
    openTargetedFaqItem();
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled();
  });

  it("ignores hashes that match nothing", () => {
    window.location.hash = "#does-not-exist";
    expect(() => openTargetedFaqItem()).not.toThrow();
  });
});
