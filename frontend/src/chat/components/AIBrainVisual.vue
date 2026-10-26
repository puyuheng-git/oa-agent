<script setup lang="ts">
/** 轻量 SVG 神经网络大脑：无外部图片依赖，支持 prefers-reduced-motion */
</script>

<template>
  <div class="brain" aria-hidden="true">
    <div class="glow" />
    <svg class="svg" viewBox="0 0 320 280" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="brainFill" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#EAF5FF" />
          <stop offset="55%" stop-color="#B8DFFA" />
          <stop offset="100%" stop-color="#008AE7" stop-opacity="0.85" />
        </linearGradient>
        <linearGradient id="lineGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#008AE7" stop-opacity="0.15" />
          <stop offset="50%" stop-color="#008AE7" stop-opacity="0.75" />
          <stop offset="100%" stop-color="#ffffff" stop-opacity="0.9" />
        </linearGradient>
        <filter id="softGlow" x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <!-- 抽象脑轮廓 -->
      <path
        class="outline"
        d="M160 36c-38 0-68 22-78 52-18 6-34 24-34 50 0 22 12 40 30 48-2 10-2 22 4 32 10 18 34 28 58 28h10c28 0 52-12 62-32 18-6 34-24 34-48 0-20-10-36-26-44 2-8 2-18-2-28C208 52 186 36 160 36z"
        fill="url(#brainFill)"
        stroke="#008AE7"
        stroke-width="1.5"
        opacity="0.92"
      />

      <!-- 半球分界与神经网络 -->
      <g class="net" stroke="url(#lineGrad)" stroke-width="1" fill="none">
        <path d="M160 52v168" opacity="0.35" />
        <path d="M98 88c22 18 40 22 62 22s40-4 62-22" opacity="0.55" />
        <path d="M86 128c28 14 48 18 74 18s46-4 74-18" opacity="0.45" />
        <path d="M96 168c24 12 42 16 64 16s40-4 64-16" opacity="0.4" />
        <path d="M112 70c18 28 20 58 18 98" opacity="0.35" />
        <path d="M208 70c-18 28-20 58-18 98" opacity="0.35" />
        <path d="M130 100l30 28 30-28" opacity="0.5" />
        <path d="M118 150l42 22 42-22" opacity="0.45" />
        <path d="M140 120l20 40" opacity="0.4" />
        <path d="M180 120l-20 40" opacity="0.4" />
      </g>

      <!-- 节点 -->
      <g class="nodes" filter="url(#softGlow)">
        <circle class="n n1" cx="160" cy="72" r="4.5" />
        <circle class="n n2" cx="118" cy="100" r="3.5" />
        <circle class="n n3" cx="202" cy="100" r="3.5" />
        <circle class="n n4" cx="100" cy="138" r="3" />
        <circle class="n n5" cx="160" cy="128" r="5" />
        <circle class="n n6" cx="220" cy="138" r="3" />
        <circle class="n n7" cx="128" cy="172" r="3.5" />
        <circle class="n n8" cx="192" cy="172" r="3.5" />
        <circle class="n n9" cx="160" cy="198" r="4" />
        <circle class="n n10" cx="145" cy="148" r="2.5" />
        <circle class="n n11" cx="175" cy="148" r="2.5" />
      </g>

      <!-- 粒子光点 -->
      <g class="particles" fill="#fff">
        <circle class="p p1" cx="90" cy="110" r="1.6" />
        <circle class="p p2" cx="230" cy="120" r="1.4" />
        <circle class="p p3" cx="150" cy="90" r="1.2" />
        <circle class="p p4" cx="175" cy="210" r="1.5" />
        <circle class="p p5" cx="125" cy="200" r="1.2" />
      </g>
    </svg>
  </div>
</template>

<style scoped>
.brain {
  position: relative;
  width: min(88px, 28vw);
  aspect-ratio: 320 / 280;
  margin: 0 auto;
}
.brain::before,
.brain::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  border-radius: 50%;
  border: 1px solid rgba(0, 138, 231, 0.14);
  transform: translate(-50%, -50%);
  pointer-events: none;
}
.brain::before {
  width: 92%;
  height: 86%;
  animation: orbit 12s linear infinite;
}
.brain::after {
  width: 108%;
  height: 100%;
  border-style: dashed;
  opacity: 0.4;
  animation: orbit 18s linear infinite reverse;
}
.glow {
  position: absolute;
  inset: 8% 14%;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(0, 138, 231, 0.34), transparent 68%);
  filter: blur(10px);
  animation: breathe 4.5s ease-in-out infinite;
}
.svg {
  position: relative;
  width: 100%;
  height: 100%;
  display: block;
}
.outline {
  animation: breathe 4.5s ease-in-out infinite;
}
.n {
  fill: #008ae7;
  stroke: #fff;
  stroke-width: 1;
}
.n5 {
  fill: #0075c7;
}
.n1,
.n5,
.n9 {
  animation: blink 2.8s ease-in-out infinite;
}
.n2,
.n6,
.n10 {
  animation: blink 3.2s ease-in-out 0.4s infinite;
}
.n3,
.n7,
.n11 {
  animation: blink 2.6s ease-in-out 0.8s infinite;
}
.n4,
.n8 {
  animation: blink 3.6s ease-in-out 1.2s infinite;
}
.p {
  opacity: 0.85;
  animation: float 5s ease-in-out infinite;
}
.p2 {
  animation-delay: 0.6s;
}
.p3 {
  animation-delay: 1.2s;
}
.p4 {
  animation-delay: 1.8s;
}
.p5 {
  animation-delay: 2.2s;
}

@keyframes breathe {
  0%,
  100% {
    transform: scale(1);
    opacity: 0.9;
  }
  50% {
    transform: scale(1.03);
    opacity: 1;
  }
}
@keyframes blink {
  0%,
  100% {
    opacity: 0.55;
  }
  50% {
    opacity: 1;
  }
}
@keyframes float {
  0%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  50% {
    transform: translateY(-6px);
    opacity: 1;
  }
}
@keyframes orbit {
  to {
    transform: translate(-50%, -50%) rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .glow,
  .outline,
  .n,
  .p,
  .brain::before,
  .brain::after {
    animation: none !important;
  }
}
</style>
