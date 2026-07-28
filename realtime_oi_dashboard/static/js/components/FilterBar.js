export function createFilterBar({
  elements,
  filters,
  favorites,
  onChange,
  signal,
}) {
  elements.searchInput.addEventListener("input", () => {
    if (filters.setQuery(elements.searchInput.value.trim().toUpperCase())) onChange();
  }, { signal });

  elements.limitSelect.addEventListener("change", () => {
    if (filters.setLimit(elements.limitSelect.value)) onChange();
  }, { signal });

  elements.oiValueFilter.addEventListener("change", () => {
    if (filters.setMinOiValue(elements.oiValueFilter.value)) onChange();
  }, { signal });

  elements.volumeFilter.addEventListener("change", () => {
    if (filters.setMinVolume(elements.volumeFilter.value)) onChange();
  }, { signal });

  elements.favoritesOnlyBtn.addEventListener("click", () => {
    filters.toggleFavoritesOnly();
    render();
    onChange();
  }, { signal });

  function render() {
    const state = filters.getState();
    elements.favoritesOnlyBtn.classList.toggle("active", state.favoritesOnly);
    elements.favoritesOnlyBtn.setAttribute(
      "aria-pressed",
      String(state.favoritesOnly),
    );
    elements.favoritesOnlyBtn.textContent = state.favoritesOnly
      ? `收藏 ${favorites.size}`
      : "只看收藏";
  }

  return { render };
}
