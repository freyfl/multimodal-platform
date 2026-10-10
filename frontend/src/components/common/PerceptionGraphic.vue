<template>
  <svg class="perception-graphic" :class="{ animated }" viewBox="0 0 440 220" fill="none" aria-hidden="true">
    <defs>
      <linearGradient id="pg-scan" x1="0" x2="1" y1="0" y2="0">
        <stop offset="0" stop-color="currentColor" stop-opacity="0"/>
        <stop offset=".5" stop-color="currentColor" stop-opacity=".22"/>
        <stop offset="1" stop-color="currentColor" stop-opacity="0"/>
      </linearGradient>
      <clipPath id="pg-field"><rect x="20" y="25" width="400" height="175"/></clipPath>
    </defs>
    <g class="field-grid" stroke="currentColor" stroke-width=".7">
      <path d="M20 185H420M45 150H395M70 115H370M95 80H345M120 45H320"/>
      <path d="M30 200L160 25M105 200L190 25M180 200L220 25M255 200L250 25M330 200L280 25M405 200L310 25"/>
    </g>
    <g class="scan-beam" clip-path="url(#pg-field)">
      <rect x="20" y="25" width="36" height="175" fill="url(#pg-scan)"/>
    </g>
    <g class="object-box" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round">
      <path class="draw" pathLength="1" d="M136 96L202 110V172L136 158ZM136 96L165 74L231 88L202 110M202 172L231 150V88M165 74V136L231 150M165 136L136 158"/>
      <path class="draw draw-2" pathLength="1" d="M283 87L315 93V128L283 122ZM283 87L298 76L330 82L315 93M315 128L330 117V82" opacity=".65"/>
    </g>
    <g class="frame-corners" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <path class="draw draw-3" pathLength="1" d="M115 81V67H129M234 67H248V81M115 171V185H129M234 185H248V171"/>
    </g>
    <g fill="currentColor" class="field-labels">
      <text x="115" y="54">PERCEPTION FIELD</text>
      <text x="264" y="166">x · y · z</text>
      <text x="22" y="216">IMAGE / VIDEO / SEMANTICS</text>
      <circle class="anchor" cx="202" cy="110" r="3"/>
      <circle class="anchor anchor-2" cx="315" cy="93" r="2.5"/>
    </g>
  </svg>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ animated?: boolean }>(), { animated: true })
</script>

<style scoped>
.perception-graphic { width: 100%; height: auto; color: var(--mint-deep); overflow: visible; }
.field-grid { opacity: .18; }
.object-box { opacity: .85; }
.frame-corners { color: var(--color-primary); }
.field-labels { font: 8px var(--font-mono); letter-spacing: 1.5px; opacity: .75; }
.scan-beam { opacity: 0; }

/* Entry: field fades, boxes draw themselves, labels settle, then a slow scan loops. */
.animated .field-grid { animation: fadeIn 1.2s var(--ease-out) both; }
.animated .draw {
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: drawStroke 1.4s var(--ease-in-out) .25s both;
}
.animated .draw-2 { animation-delay: .55s; animation-duration: 1.1s; }
.animated .draw-3 { animation-delay: .9s; animation-duration: .9s; }
.animated .field-labels { animation: fadeIn .8s var(--ease-out) 1.1s both; }
.animated .anchor { transform-origin: center; transform-box: fill-box; animation: anchorPop .6s var(--ease-spring) 1.3s both; }
.animated .anchor-2 { animation-delay: 1.45s; }
.animated .scan-beam {
  animation: scanLoop 6s var(--ease-in-out) 2.2s infinite;
}

@keyframes anchorPop {
  from { transform: scale(0); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}
@keyframes scanLoop {
  0% { transform: translateX(-40px); opacity: 0; }
  12% { opacity: 1; }
  68% { opacity: 1; }
  80% { transform: translateX(404px); opacity: 0; }
  100% { transform: translateX(404px); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .animated .draw { stroke-dasharray: none; stroke-dashoffset: 0; animation: none; }
  .animated .scan-beam { display: none; }
}
</style>
