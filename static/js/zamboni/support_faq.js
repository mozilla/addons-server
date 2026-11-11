// Open the FAQ entry targeted by the URL hash on the support page, so links
// like /developers/support#api-key-rate-limit land on an expanded answer.
export function openTargetedFaqItem() {
  const id = decodeURIComponent(window.location.hash.slice(1));
  if (!id) {
    return;
  }
  const item = document.getElementById(id);
  if (item && item.matches("details.faq-item")) {
    item.open = true;
    item.scrollIntoView();
  }
}

document.addEventListener("DOMContentLoaded", openTargetedFaqItem);
window.addEventListener("hashchange", openTargetedFaqItem);
