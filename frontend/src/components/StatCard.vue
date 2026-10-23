<script setup>
/*
 * 指标卡：标签、数值（带单位）和一行补充说明。
 * 数值缺失时显示"暂无数据"，不显示 0，避免把缺失误读为零浓度。
 */
import { computed } from 'vue'
import { EMPTY } from '../lib/format'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: null },
  unit: { type: String, default: '' },
  hint: { type: String, default: '' },
  icon: { type: [Object, Function], default: null },
  featured: { type: Boolean, default: false },
  word: { type: Boolean, default: false },
})

const missing = computed(() => {
  return props.value === null || props.value === undefined || props.value === EMPTY
})
</script>

<template>
  <article class="stat" :class="{ featured }">
    <div class="stat-label">
      <span>{{ label }}</span>
      <component :is="icon" v-if="icon" :size="16" aria-hidden="true" />
    </div>
    <div v-if="missing" class="stat-value word muted">暂无数据</div>
    <div v-else class="stat-value" :class="{ word }">
      {{ value }}<small v-if="unit">{{ unit }}</small>
    </div>
    <div v-if="hint || $slots.default" class="stat-hint">
      <slot>{{ hint }}</slot>
    </div>
  </article>
</template>
