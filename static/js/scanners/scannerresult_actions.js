document.querySelectorAll('.report-false-positive-button').forEach((button) => {
  button.addEventListener('click', () => {
    const actionsTag = document.getElementById('scannerresult_actions');
    const refreshURL = actionsTag ? actionsTag.dataset.refreshUrl : null;

    setTimeout(() => {
      if (typeof refreshURL === 'string') {
        window.location.href = refreshURL;
      } else {
        window.location.reload();
      }
    }, 2000); // 2 seconds
  });
});
