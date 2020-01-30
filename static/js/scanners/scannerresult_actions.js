document.querySelectorAll('.report-false-positive-button').forEach((button) => {
  button.addEventListener('click', () => {
    setTimeout(() => {
      window.location.reload();
    }, 2000); // 2 seconds
  });
});
