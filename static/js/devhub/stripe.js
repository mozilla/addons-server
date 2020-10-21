const checkoutButton = document.getElementById('checkout-button');

if (checkoutButton && checkoutButton.dataset) {
  const stripe = Stripe(checkoutButton.dataset['publickey']);

  checkoutButton.addEventListener('click', function () {
    stripe.redirectToCheckout({
      sessionId: checkoutButton.dataset['sessionid'],
    });
  });
}
