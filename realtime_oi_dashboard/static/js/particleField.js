const TARGET_FRAME_MS = 1000 / 30;
const MIN_PARTICLES = 28;
const MAX_PARTICLES = 60;
const PIXELS_PER_PARTICLE = 36000;
const MAX_DEVICE_PIXEL_RATIO = 1.5;
const LINK_DISTANCE = 118;
const COLORS = [
  "86, 231, 255",
  "111, 140, 255",
  "168, 113, 255",
];

export function createParticleField(canvas) {
  const context = canvas?.getContext("2d", { alpha: true });
  if (!context) return { dispose() {} };

  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let particles = [];
  let width = 0;
  let height = 0;
  let animationFrame = 0;
  let resizeFrame = 0;
  let previousFrameAt = 0;
  let disposed = false;

  window.addEventListener("resize", scheduleResize);
  document.addEventListener("visibilitychange", syncAnimation);
  reducedMotion?.addEventListener("change", syncAnimation);
  resize();
  syncAnimation();

  function resize() {
    resizeFrame = 0;
    const previousWidth = width;
    const previousHeight = height;
    width = window.innerWidth;
    height = window.innerHeight;

    const pixelRatio = Math.min(
      window.devicePixelRatio || 1,
      MAX_DEVICE_PIXEL_RATIO,
    );
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

    if (previousWidth && previousHeight) {
      const scaleX = width / previousWidth;
      const scaleY = height / previousHeight;
      for (const particle of particles) {
        particle.x *= scaleX;
        particle.y *= scaleY;
      }
    }

    const particleCount = clamp(
      Math.round(width * height / PIXELS_PER_PARTICLE),
      MIN_PARTICLES,
      MAX_PARTICLES,
    );
    while (particles.length < particleCount) particles.push(createParticle());
    particles.length = particleCount;
    draw();
  }

  function createParticle() {
    const direction = Math.random() * Math.PI * 2;
    const speed = 0.1 + Math.random() * 0.14;
    return {
      x: Math.random() * width,
      y: Math.random() * height,
      vx: Math.cos(direction) * speed,
      vy: Math.sin(direction) * speed,
      radius: 0.9 + Math.random() * 1.1,
      opacity: 0.35 + Math.random() * 0.5,
      phase: Math.random() * Math.PI * 2,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
    };
  }

  function animate(timestamp) {
    animationFrame = window.requestAnimationFrame(animate);
    if (timestamp - previousFrameAt < TARGET_FRAME_MS) return;

    const elapsed = previousFrameAt
      ? Math.min((timestamp - previousFrameAt) / TARGET_FRAME_MS, 2)
      : 1;
    previousFrameAt = timestamp;

    for (const particle of particles) {
      particle.x += particle.vx * elapsed;
      particle.y += particle.vy * elapsed;
      particle.phase += 0.012 * elapsed;
      wrapParticle(particle);
    }
    draw();
  }

  function draw() {
    context.clearRect(0, 0, width, height);
    drawLinks();

    for (const particle of particles) {
      const pulse = 0.72 + Math.sin(particle.phase) * 0.28;
      const opacity = particle.opacity * pulse;

      context.beginPath();
      context.fillStyle = `rgba(${particle.color}, ${opacity * 0.2})`;
      context.arc(particle.x, particle.y, particle.radius * 4.2, 0, Math.PI * 2);
      context.fill();

      context.beginPath();
      context.fillStyle = `rgba(${particle.color}, ${opacity})`;
      context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
      context.fill();
    }
  }

  function drawLinks() {
    const maximumDistanceSquared = LINK_DISTANCE ** 2;
    context.lineWidth = 0.6;

    for (let index = 0; index < particles.length; index += 1) {
      const first = particles[index];
      for (let next = index + 1; next < particles.length; next += 1) {
        const second = particles[next];
        const xDistance = first.x - second.x;
        const yDistance = first.y - second.y;
        const distanceSquared = xDistance ** 2 + yDistance ** 2;
        if (distanceSquared > maximumDistanceSquared) continue;

        const distance = Math.sqrt(distanceSquared);
        const opacity = (1 - distance / LINK_DISTANCE) * 0.14;
        context.beginPath();
        context.strokeStyle = `rgba(116, 155, 255, ${opacity})`;
        context.moveTo(first.x, first.y);
        context.lineTo(second.x, second.y);
        context.stroke();
      }
    }
  }

  function wrapParticle(particle) {
    const margin = LINK_DISTANCE / 2;
    if (particle.x < -margin) particle.x = width + margin;
    if (particle.x > width + margin) particle.x = -margin;
    if (particle.y < -margin) particle.y = height + margin;
    if (particle.y > height + margin) particle.y = -margin;
  }

  function scheduleResize() {
    if (resizeFrame) return;
    resizeFrame = window.requestAnimationFrame(resize);
  }

  function syncAnimation() {
    stopAnimation();
    if (disposed || document.hidden || reducedMotion?.matches) {
      draw();
      return;
    }
    previousFrameAt = 0;
    animationFrame = window.requestAnimationFrame(animate);
  }

  function stopAnimation() {
    if (!animationFrame) return;
    window.cancelAnimationFrame(animationFrame);
    animationFrame = 0;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    stopAnimation();
    if (resizeFrame) window.cancelAnimationFrame(resizeFrame);
    window.removeEventListener("resize", scheduleResize);
    document.removeEventListener("visibilitychange", syncAnimation);
    reducedMotion?.removeEventListener("change", syncAnimation);
  }

  return { dispose };
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum);
}
