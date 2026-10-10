<template>
  <div class="auth-layout">
    <section class="auth-story" aria-label="多模态数据工作台">
      <div class="auth-wordmark reveal" style="--d: 0ms">
        <span class="wordmark-symbol">M<span> / </span>M</span>
        <span>多模态检索平台</span>
      </div>
      <div class="story-content">
        <span class="story-kicker reveal" style="--d: 120ms">THE MULTIMODAL WORKSPACE</span>
        <h2>
          <span class="line"><span class="line-inner" style="--d: 220ms">看见数据。</span></span>
          <span class="line"><span class="line-inner" style="--d: 340ms">理解每一帧<span class="accent">。</span></span></span>
        </h2>
        <p class="reveal" style="--d: 520ms">连接图像、视频与语义。<br>让自动驾驶数据的导入、标注与检索，井然有序。</p>
        <PerceptionGraphic class="story-graphic reveal" style="--d: 640ms" />
      </div>
      <div class="story-footer reveal" style="--d: 800ms">
        <span>感知 / 理解 / 检索</span>
        <span class="footer-coords">LAT 39.90 · LNG 116.40</span>
        <span>AUTODRIVE</span>
      </div>
    </section>
    <main class="auth-form-region">
      <div class="auth-form-stack">
        <slot />
      </div>
      <p class="auth-caption">多模态数据，尽在一个工作空间。</p>
    </main>
  </div>
</template>

<script setup lang="ts">
import PerceptionGraphic from '@/components/common/PerceptionGraphic.vue'
</script>

<style scoped>
.auth-layout {
  display: grid;
  grid-template-columns: 1.05fr 1fr;
  min-height: 100dvh;
  background: var(--color-bg-page);
}

.auth-story {
  position: relative;
  isolation: isolate;
  background: var(--ink);
  color: #edf4ef;
  padding: 40px var(--page-gutter);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
}
.auth-story::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: -1;
  background-image:
    linear-gradient(rgba(196, 236, 207, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(196, 236, 207, 0.07) 1px, transparent 1px);
  background-size: 48px 48px;
  -webkit-mask-image: radial-gradient(ellipse 75% 65% at 95% 10%, rgba(0, 0, 0, .9), transparent 70%);
  mask-image: radial-gradient(ellipse 75% 65% at 95% 10%, rgba(0, 0, 0, .9), transparent 70%);
}
.auth-story::after {
  content: '';
  position: absolute;
  z-index: -1;
  width: 520px;
  height: 520px;
  right: -200px;
  top: -160px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(196, 236, 207, 0.14), transparent 65%);
  pointer-events: none;
}

.auth-wordmark { display: flex; align-items: center; gap: 18px; font-size: 13px; letter-spacing: 0.04em; }
.wordmark-symbol { font: 600 24px/1 var(--font-heading); letter-spacing: -2px; color: #edf5f0; }
.wordmark-symbol span { color: var(--mint); }

.story-content { margin: 56px 0 32px; max-width: 620px; }
.story-kicker { display: inline-block; color: #b1c6bd; font: 500 10px var(--font-mono); letter-spacing: var(--tracking-eyebrow); }
.story-content h2 {
  color: #edf4ef;
  font-size: clamp(38px, 4.2vw, 68px);
  font-weight: 500;
  line-height: 1.25;
  letter-spacing: -0.02em;
  margin: 22px 0 26px;
}
.story-content h2 .accent { color: var(--mint); }
.story-content p { color: #afc0bd; font-size: 14px; line-height: 2; }
.story-graphic { color: var(--mint); max-width: 480px; margin-top: 36px; }
.story-graphic :deep(.frame-corners) { color: var(--mint); }
.story-graphic :deep(.perception-graphic) { color: var(--mint); }
.story-graphic :deep(.field-grid) { opacity: .11; }

.story-footer {
  display: flex;
  justify-content: space-between;
  color: #9eafac;
  font: 500 10px var(--font-mono);
  letter-spacing: 0.1em;
  gap: 24px;
}
.footer-coords { opacity: .6; }

.auth-form-region {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 40px 24px;
}
.auth-form-stack { width: 100%; display: flex; justify-content: center; }
.auth-caption {
  margin-top: 40px;
  font: 500 10px var(--font-mono);
  letter-spacing: 0.14em;
  color: var(--gray-400);
  animation: fadeIn .8s var(--ease-out) .9s both;
}

/* Reveal choreography */
.reveal { animation: fadeInUp .8s var(--ease-out) var(--d, 0ms) both; }
.line { display: block; overflow: hidden; padding-bottom: .08em; margin-bottom: -.08em; }
.line-inner { display: block; animation: maskReveal .9s var(--ease-out) var(--d, 0ms) both; }

@media (max-width: 960px) {
  .auth-layout { grid-template-columns: .85fr 1fr; }
  .auth-story { padding: 32px; }
  .story-content h2 { font-size: 38px; }
  .footer-coords { display: none; }
}
@media (max-width: 700px) {
  .auth-layout { display: block; }
  .auth-story { padding: 20px 24px; }
  .story-content, .story-footer { display: none; }
  .auth-form-region { min-height: calc(100dvh - 72px); padding: 32px 20px; }
  .auth-caption { margin-top: 28px; }
}
@media (prefers-reduced-motion: reduce) {
  .reveal, .line-inner, .auth-caption { animation: none; }
}
</style>
