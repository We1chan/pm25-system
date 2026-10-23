<script setup>
/*
 * 地图点颜色的图例：PM2.5 小时浓度分档（μg/m³）。
 * 颜色只表示浓度高低，不代表官方空气质量等级发布。
 */
import { pmBins } from '../lib/chart'
</script>

<template>
  <div class="pm-legend" aria-label="地图颜色图例">
    <span class="title">PM₂.₅ 小时浓度 μg/m³</span>
    <span v-for="bin in pmBins" :key="bin.label" class="item">
      <i class="swatch" :style="{ background: bin.color }"></i>{{ bin.label }}
    </span>
    <span class="item"><i class="swatch missing"></i>无实测</span>
  </div>
</template>

<style scoped>
.pm-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--ink-2);
}

.title {
  color: var(--ink-3);
}

.item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.swatch {
  border-radius: 50%;
}

.missing {
  background: #b9c0ba;
}
</style>
