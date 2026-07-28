const MOTION_MODULE_URL =
  "https://cdn.jsdelivr.net/npm/motion@12.42.2/+esm";
const VALUE_PULSE_DURATION = 0.38;
const MAX_REVEALED_ROWS = 20;

export function createMotionEffects() {
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const activeAnimations = new Set();
  let motionPromise = null;
  let disposed = false;
  let paused = document.hidden || !document.hasFocus();

  reducedMotion?.addEventListener("change", handleMotionPreference);

  function loadMotion() {
    if (disposed || paused || reducedMotion?.matches) return Promise.resolve(null);
    if (!motionPromise) {
      motionPromise = import(MOTION_MODULE_URL).catch(() => null);
    }
    return motionPromise;
  }

  function playEntrance() {
    run(({ animate, stagger }) => {
      const hero = document.querySelector("[data-motion='hero'] .hero-copy");
      const status = document.querySelector("[data-motion='status']");
      const metrics = document.querySelectorAll("[data-motion='metric']");
      const panels = document.querySelectorAll("[data-motion='panel']");

      track(animate(
        hero,
        { opacity: [0, 1], y: [22, 0] },
        { duration: 0.72, ease: [0.22, 1, 0.36, 1] },
      ));
      track(animate(
        status,
        { opacity: [0, 1], x: [24, 0] },
        { duration: 0.62, delay: 0.08, ease: [0.22, 1, 0.36, 1] },
      ));
      track(animate(
        metrics,
        { opacity: [0, 1], y: [18, 0], scale: [0.97, 1] },
        {
          duration: 0.55,
          delay: stagger(0.07, { startDelay: 0.14 }),
          ease: [0.22, 1, 0.36, 1],
        },
      ));
      track(animate(
        panels,
        { opacity: [0, 1], y: [24, 0] },
        {
          duration: 0.65,
          delay: stagger(0.09, { startDelay: 0.34 }),
          ease: [0.22, 1, 0.36, 1],
        },
      ));
    });
  }

  function pulseValues(elements) {
    const values = [...new Set(elements)].filter(Boolean);
    if (!values.length) return;

    run(({ animate, stagger }) => {
      track(animate(
        values,
        {
          scale: [1, 1.075, 1],
          filter: ["brightness(1)", "brightness(1.4)", "brightness(1)"],
        },
        {
          duration: VALUE_PULSE_DURATION,
          delay: stagger(0.025),
          ease: [0.22, 1, 0.36, 1],
        },
      ));
    });
  }

  function revealRows(rows) {
    const visibleRows = rows.slice(0, MAX_REVEALED_ROWS);
    if (!visibleRows.length) return;

    run(({ animate, stagger }) => {
      track(animate(
        visibleRows,
        { opacity: [0, 1], y: [10, 0] },
        {
          duration: 0.34,
          delay: stagger(0.018),
          ease: [0.22, 1, 0.36, 1],
        },
      ));
    });
  }

  function popFavorite(button) {
    run(({ animate }) => {
      track(animate(
        button,
        { scale: [1, 0.72, 1.22, 1], rotate: [0, -10, 7, 0] },
        { duration: 0.46, ease: [0.22, 1, 0.36, 1] },
      ));
    });
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    reducedMotion?.removeEventListener("change", handleMotionPreference);
    stopAnimations();
  }

  function setPaused(nextPaused) {
    paused = Boolean(nextPaused);
    if (paused) stopAnimations();
  }

  function run(callback) {
    if (disposed || paused || reducedMotion?.matches) return;
    void loadMotion()
      .then(motion => {
        if (!motion || disposed || paused || reducedMotion?.matches) return;
        callback(motion);
      })
      .catch(() => {});
  }

  function track(animation) {
    if (!animation) return;
    activeAnimations.add(animation);
    if (typeof animation.then === "function") {
      animation.then(
        () => activeAnimations.delete(animation),
        () => activeAnimations.delete(animation),
      );
    }
  }

  function handleMotionPreference(event) {
    if (event.matches) stopAnimations();
  }

  function stopAnimations() {
    for (const animation of activeAnimations) {
      animation.stop?.();
    }
    activeAnimations.clear();
  }

  void loadMotion();

  return {
    dispose,
    playEntrance,
    popFavorite,
    pulseValues,
    revealRows,
    setPaused,
  };
}
