"use strict";

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const particleColors = ["#f3a7c8", "#c8aff0", "#9acbf0", "#9ce1c1", "#f0df92"];
const maxParticles = 48;
let activeParticles = 0;

function sparkle(x, y) {
  if (reducedMotion.matches) {
    return;
  }
  const count = 4 + Math.floor(Math.random() * 5);
  for (let index = 0; index < count && activeParticles < maxParticles; index += 1) {
    const angle = (Math.PI * 2 * index) / count + Math.random() * 0.5;
    const distance = 16 + Math.random() * 28;
    const particle = document.createElement("span");
    particle.className = "fairy-particle";
    particle.style.left = `${x}px`;
    particle.style.top = `${y}px`;
    particle.style.background = particleColors[Math.floor(Math.random() * particleColors.length)];
    particle.style.setProperty("--particle-x", `${Math.cos(angle) * distance}px`);
    particle.style.setProperty("--particle-y", `${Math.sin(angle) * distance}px`);
    particle.style.setProperty("--particle-turn", `${Math.floor(Math.random() * 180) + 90}deg`);
    activeParticles += 1;
    particle.addEventListener("animationend", () => {
      particle.remove();
      activeParticles -= 1;
    }, { once: true });
    document.body.append(particle);
  }
}

const cardObserver = reducedMotion.matches || !("IntersectionObserver" in window)
  ? null
  : new IntersectionObserver((entries, observer) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) {
          continue;
        }
        entry.target.classList.add("card-glint");
        entry.target.addEventListener("animationend", () => {
          entry.target.classList.remove("card-glint");
        }, { once: true });
        observer.unobserve(entry.target);
      }
    }, { rootMargin: "0px 0px -8%", threshold: 0.16 });

function observeCard(card) {
  cardObserver?.observe(card);
}

function markNew(card) {
  if (reducedMotion.matches) {
    return;
  }
  card.classList.add("media-card-new");
  card.addEventListener("animationend", () => card.classList.remove("media-card-new"), {
    once: true,
  });
  const bounds = card.getBoundingClientRect();
  sparkle(bounds.right - 12, bounds.top + 12);
}

document.addEventListener("pointerdown", (event) => {
  if (!event.isPrimary || (event.pointerType === "mouse" && event.button !== 0)) {
    return;
  }
  sparkle(event.clientX, event.clientY);
}, { passive: true });

window.fairyEffects = { observeCard, markNew };
