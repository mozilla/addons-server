// Enable pan/zoom on all Graphviz SVGs after the DOM is loaded
// Requires panzoom.min.js to be loaded first

document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  let active = params.has('zoom');
  let graph = document.querySelector('.panzoom-graph');
  let container = graph?.parentElement;

  if (!window.panzoom || !graph || !container) return;

  function toggleZoom(active) {
    if (active) {
      params.set('zoom', '');
    } else {
      params.delete('zoom');
    }
    window.location.search = params.toString();
  }

  if (!active) {
    return graph.addEventListener('click', (e) => {
      e.preventDefault();
      toggleZoom(true);
    });
  }

  function initToggleButton() {
    let btn = document.createElement('button');
    btn.id = 'panzoom-toggle';
    btn.classList.add('btn', 'btn-neutral');
    btn.textContent = 'Go Back';
    container.appendChild(btn);
    return btn;
  }

  let toggleButton = initToggleButton();

  container.style.position = 'fixed';
  container.style.top = '0';
  container.style.left = '0';
  container.style.width = '100vw';
  container.style.height = '100vh';
  container.style.backgroundColor = 'white';
  container.style.zIndex = '1000';

  toggleButton.style.position = 'fixed';
  toggleButton.style.top = '10px';
  toggleButton.style.right = '10px';

  window.panzoom(graph, {
    initialX: 0,
    initialY: 0,
    initialZoom: 1,
    minZoom: 1,
    transformOrigin: {x: 0, y: 0},
  });

  toggleButton.addEventListener('click', () => {
    toggleZoom(false);
  });
});
