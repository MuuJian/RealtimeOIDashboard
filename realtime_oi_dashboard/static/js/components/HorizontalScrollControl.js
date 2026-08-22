const MIN_THUMB_WIDTH = 48;
const KEYBOARD_SCROLL_STEP = 80;
const SCROLL_EPSILON = 1;

export function createHorizontalScrollControl({
  viewport,
  track,
  thumb,
  scrollElement,
  shell,
}) {
  let disposed = false;
  let maximum = 0;
  let thumbTravel = 0;
  let thumbWidth = 0;
  let dragging = false;
  let activePointerId = null;
  let dragStartX = 0;
  let dragStartScrollLeft = 0;
  const resizeObserver = typeof ResizeObserver === "function"
    ? new ResizeObserver(updateMetrics)
    : null;

  viewport.addEventListener("scroll", syncFromViewport, { passive: true });
  track.addEventListener("pointerdown", startPointerInteraction);
  track.addEventListener("pointermove", continuePointerInteraction);
  track.addEventListener("pointerup", finishPointerInteraction);
  track.addEventListener("pointercancel", finishPointerInteraction);
  track.addEventListener("lostpointercapture", finishPointerInteraction);
  track.addEventListener("keydown", handleKeydown);
  if (resizeObserver) {
    resizeObserver.observe(viewport);
    resizeObserver.observe(track);
    if (viewport.firstElementChild) {
      resizeObserver.observe(viewport.firstElementChild);
    }
  } else {
    window.addEventListener("resize", updateMetrics);
  }

  updateMetrics();

  function updateMetrics() {
    if (disposed) return;
    const measuredMaximum = getMaximum();
    const scrollable = measuredMaximum > SCROLL_EPSILON;
    maximum = scrollable ? measuredMaximum : 0;
    scrollElement.hidden = !scrollable;
    shell.classList.toggle("is-scrollable", scrollable);

    const trackWidth = Math.max(0, track.clientWidth);
    const visibleRatio = viewport.scrollWidth > 0
      ? Math.min(1, viewport.clientWidth / viewport.scrollWidth)
      : 1;
    thumbWidth = Math.min(
      trackWidth,
      Math.max(MIN_THUMB_WIDTH, Math.round(trackWidth * visibleRatio)),
    );
    thumbTravel = Math.max(0, trackWidth - thumbWidth);
    thumb.style.width = `${thumbWidth}px`;
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", String(Math.round(maximum)));
    syncFromViewport();
  }

  function syncFromViewport() {
    if (disposed) return;
    const scrollLeft = clamp(viewport.scrollLeft, 0, maximum);
    const thumbLeft = maximum > 0
      ? (scrollLeft / maximum) * thumbTravel
      : 0;
    thumb.style.transform = `translateX(${thumbLeft}px)`;
    track.setAttribute("aria-valuenow", String(Math.round(scrollLeft)));
  }

  function startPointerInteraction(event) {
    if (disposed || maximum <= 0 || (event.button ?? 0) !== 0) return;
    event.preventDefault();
    track.focus?.({ preventScroll: true });

    if (event.target !== thumb && !thumb.contains?.(event.target)) {
      const trackLeft = track.getBoundingClientRect().left;
      const nextThumbLeft = clamp(
        event.clientX - trackLeft - (thumbWidth / 2),
        0,
        thumbTravel,
      );
      setScrollFromThumbLeft(nextThumbLeft);
    }

    dragging = true;
    activePointerId = event.pointerId;
    dragStartX = event.clientX;
    dragStartScrollLeft = viewport.scrollLeft;
    track.classList.add("is-dragging");
    track.setPointerCapture?.(event.pointerId);
  }

  function continuePointerInteraction(event) {
    if (!dragging || event.pointerId !== activePointerId) return;
    event.preventDefault();
    const scrollPerPixel = thumbTravel > 0 ? maximum / thumbTravel : 0;
    setScrollLeft(
      dragStartScrollLeft + ((event.clientX - dragStartX) * scrollPerPixel),
    );
  }

  function finishPointerInteraction(event) {
    if (!dragging || event.pointerId !== activePointerId) return;
    dragging = false;
    activePointerId = null;
    track.classList.remove("is-dragging");
    if (track.hasPointerCapture?.(event.pointerId)) {
      track.releasePointerCapture?.(event.pointerId);
    }
  }

  function handleKeydown(event) {
    let nextScrollLeft;
    switch (event.key) {
      case "ArrowLeft":
        nextScrollLeft = viewport.scrollLeft - KEYBOARD_SCROLL_STEP;
        break;
      case "ArrowRight":
        nextScrollLeft = viewport.scrollLeft + KEYBOARD_SCROLL_STEP;
        break;
      case "PageUp":
        nextScrollLeft = viewport.scrollLeft - (viewport.clientWidth * .8);
        break;
      case "PageDown":
        nextScrollLeft = viewport.scrollLeft + (viewport.clientWidth * .8);
        break;
      case "Home":
        nextScrollLeft = 0;
        break;
      case "End":
        nextScrollLeft = maximum;
        break;
      default:
        return;
    }
    event.preventDefault();
    setScrollLeft(nextScrollLeft);
  }

  function setScrollFromThumbLeft(thumbLeft) {
    const ratio = thumbTravel > 0 ? thumbLeft / thumbTravel : 0;
    setScrollLeft(ratio * maximum);
  }

  function setScrollLeft(value) {
    viewport.scrollLeft = clamp(value, 0, maximum);
    syncFromViewport();
  }

  function getMaximum() {
    return Math.max(0, viewport.scrollWidth - viewport.clientWidth);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    viewport.removeEventListener("scroll", syncFromViewport);
    track.removeEventListener("pointerdown", startPointerInteraction);
    track.removeEventListener("pointermove", continuePointerInteraction);
    track.removeEventListener("pointerup", finishPointerInteraction);
    track.removeEventListener("pointercancel", finishPointerInteraction);
    track.removeEventListener("lostpointercapture", finishPointerInteraction);
    track.removeEventListener("keydown", handleKeydown);
    track.classList.remove("is-dragging");
    resizeObserver?.disconnect();
    if (!resizeObserver) {
      window.removeEventListener("resize", updateMetrics);
    }
  }

  return { dispose, updateMetrics };
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}
