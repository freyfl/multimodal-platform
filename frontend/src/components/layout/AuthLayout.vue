<template>
  <div class="auth-layout">
    <section class="auth-story" aria-label="多模态数据工作台">
      <div class="auth-wordmark"><span class="wordmark-symbol">M / M</span> 多模态检索平台</div>
      <div class="story-content">
        <span class="story-kicker">THE MULTIMODAL WORKSPACE</span>
        <h2>看见数据。<br>理解每一帧<span>。</span></h2>
        <p>连接图像、视频与语义。<br>让自动驾驶数据的导入、标注与检索，井然有序。</p>
        <PerceptionGraphic class="story-graphic" />
      </div>
      <div class="story-footer"><span>感知 / 理解 / 检索</span><span>AUTODRIVE</span></div>
    </section>
    <main class="auth-form-region">
      <slot />
      <p class="auth-caption">多模态数据，尽在一个工作空间。</p>
    </main>
  </div>
</template>

<script setup lang="ts">
import PerceptionGraphic from '@/components/common/PerceptionGraphic.vue'
</script>

<style scoped>
.auth-layout { display: grid; grid-template-columns: 1.05fr 1fr; min-height: 100dvh; background: var(--color-bg-page); }
.auth-story { background: #172126; color: #edf4ef; padding: 40px clamp(32px, 4vw, 72px); display: flex; flex-direction: column; justify-content: space-between; overflow: hidden; }
.auth-wordmark { display: flex; align-items: center; gap: 18px; font-size: 13px; }
.wordmark-symbol { color: #c4eccf; font: 600 24px var(--font-heading); letter-spacing: -2px; }
.story-content { margin: 60px 0 32px; }
.story-kicker { color: #b1c6bd; font: 10px var(--font-mono); letter-spacing: 2px; }
.story-content h2 { color: #edf4ef; font-size: clamp(36px, 4vw, 64px); font-weight: 500; line-height: 1.4; letter-spacing: -2px; margin: 24px 0; }
.story-content h2 span { color: #c4eccf; }
.story-content p { color: #afc0bd; font-size: 14px; line-height: 2; }
.story-graphic { color: #c4eccf; max-width: 480px; margin-top: 32px; }
.story-graphic :deep(.frame-corners) { color: #c4eccf; }
.story-footer { display: flex; justify-content: space-between; color: #9eafac; font: 10px var(--font-mono); letter-spacing: 1px; gap: 24px; }
.auth-form-region { display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 40px 24px; }
.auth-caption { margin-top: 40px; font-size: 11px; color: var(--gray-500); }
@media (max-width: 960px) {
  .auth-layout { grid-template-columns: .85fr 1fr; }
  .auth-story { padding: 32px; }
  .story-content h2 { font-size: 38px; }
}
@media (max-width: 700px) {
  .auth-layout { display: block; }
  .auth-story { padding: 24px; }
  .story-content, .story-footer { display: none; }
  .auth-form-region { min-height: calc(100dvh - 80px); padding: 32px 20px; }
  .auth-caption { margin-top: 28px; }
}
</style>
