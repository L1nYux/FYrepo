(() => {
  window.workbenchMessageURL = (value, root) => {
    const url = new URL(value, location.href);
    const space = (root || document.querySelector('[data-messages], [data-personal-thread]'))?.dataset.workspace;
    if (space && url.origin === location.origin && !url.searchParams.has('space')) url.searchParams.set('space', space);
    return url.href;
  };
})();
