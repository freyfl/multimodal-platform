<template>
  <svg class="perception-graphic" viewBox="0 0 440 220" fill="none" aria-hidden="true">
    <g class="field-grid" stroke="currentColor" stroke-width=".7">
      <path d="M20 185H420M45 150H395M70 115H370M95 80H345M120 45H320"/>
      <path d="M30 200L160 25M105 200L190 25M180 200L220 25M255 200L250 25M330 200L280 25M405 200L310 25"/>
    </g>
    <g class="object-box" stroke="currentColor" stroke-width="1.3">
      <path d="M136 96L202 110V172L136 158ZM136 96L165 74L231 88L202 110M202 172L231 150V88M165 74V136L231 150M165 136L136 158"/>
      <path d="M283 87L315 93V128L283 122ZM283 87L298 76L330 82L315 93M315 128L330 117V82" opacity=".65"/>
    </g>
    <g class="frame-corners" stroke="currentColor" stroke-width="2">
      <path d="M115 81V67H129M234 67H248V81M115 171V185H129M234 185H248V171"/>
    </g>
    <g fill="currentColor" class="field-labels">
      <text x="115" y="54">PERCEPTION FIELD</text>
      <text x="264" y="166">x · y · z</text>
      <text x="22" y="216">IMAGE / VIDEO / SEMANTICS</text>
      <circle cx="202" cy="110" r="3"/>
      <circle cx="315" cy="93" r="2.5"/>
    </g>
  </svg>
</template>

<style scoped>
.perception-graphic { width: 100%; height: auto; color: #42695b; }
.field-grid { opacity: .18; }
.object-box { opacity: .8; }
.frame-corners { color: var(--color-primary); }
.field-labels { font: 8px var(--font-mono); letter-spacing: 1.5px; opacity: .75; }
</style>
