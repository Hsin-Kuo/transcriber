<template>
  <!-- SVG 濾鏡定義，全局使用 -->
  <svg class="electric-svg-filters" aria-hidden="true">
    <defs>
      <!-- 電流扭曲效果濾鏡 -->
      <filter
        id="electric-turbulence"
        colorInterpolationFilters="sRGB"
        x="-20%"
        y="-20%"
        width="140%"
        height="140%"
      >
        <!-- 垂直方向噪聲 1 (向下) -->
        <feTurbulence
          type="turbulence"
          baseFrequency="0.02"
          numOctaves="10"
          result="noise1"
          seed="1"
        />
        <feOffset in="noise1" dx="0" dy="0" result="offsetNoise1">
          <animate
            attributeName="dy"
            values="700; 0"
            dur="6s"
            repeatCount="indefinite"
            calcMode="linear"
          />
        </feOffset>

        <!-- 垂直方向噪聲 2 (向上) -->
        <feTurbulence
          type="turbulence"
          baseFrequency="0.02"
          numOctaves="10"
          result="noise2"
          seed="1"
        />
        <feOffset in="noise2" dx="0" dy="0" result="offsetNoise2">
          <animate
            attributeName="dy"
            values="0; -700"
            dur="6s"
            repeatCount="indefinite"
            calcMode="linear"
          />
        </feOffset>

        <!-- 水平方向噪聲 1 (向右) -->
        <feTurbulence
          type="turbulence"
          baseFrequency="0.02"
          numOctaves="10"
          result="noise3"
          seed="2"
        />
        <feOffset in="noise3" dx="0" dy="0" result="offsetNoise3">
          <animate
            attributeName="dx"
            values="490; 0"
            dur="6s"
            repeatCount="indefinite"
            calcMode="linear"
          />
        </feOffset>

        <!-- 水平方向噪聲 2 (向左) -->
        <feTurbulence
          type="turbulence"
          baseFrequency="0.02"
          numOctaves="10"
          result="noise4"
          seed="2"
        />
        <feOffset in="noise4" dx="0" dy="0" result="offsetNoise4">
          <animate
            attributeName="dx"
            values="0; -490"
            dur="6s"
            repeatCount="indefinite"
            calcMode="linear"
          />
        </feOffset>

        <!-- 合併噪聲 -->
        <feComposite in="offsetNoise1" in2="offsetNoise2" result="part1" />
        <feComposite in="offsetNoise3" in2="offsetNoise4" result="part2" />
        <feBlend in="part1" in2="part2" mode="color-dodge" result="combinedNoise" />

        <!-- 應用位移映射 -->
        <feDisplacementMap
          in="SourceGraphic"
          in2="combinedNoise"
          scale="30"
          xChannelSelector="R"
          yChannelSelector="B"
        />
      </filter>

      <!-- 較輕微的扭曲效果（用於較小的元素） -->
      <filter
        id="electric-turbulence-subtle"
        colorInterpolationFilters="sRGB"
        x="-10%"
        y="-10%"
        width="120%"
        height="120%"
      >
        <feTurbulence
          type="turbulence"
          baseFrequency="0.015"
          numOctaves="8"
          result="noise"
          seed="3"
        />
        <feOffset in="noise" dx="0" dy="0" result="offsetNoise">
          <animate
            attributeName="dy"
            values="500; 0; -500; 0; 500"
            dur="8s"
            repeatCount="indefinite"
            calcMode="linear"
          />
        </feOffset>
        <feDisplacementMap
          in="SourceGraphic"
          in2="offsetNoise"
          scale="15"
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>
    </defs>
  </svg>
</template>

<style scoped>
.electric-svg-filters {
  position: absolute;
  width: 0;
  height: 0;
  pointer-events: none;
}
</style>
