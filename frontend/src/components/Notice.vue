<script setup>
/*
 * 提示条：info（说明）、warn（需要注意）、error（失败，必须让用户看到）、
 * good（成功）、loading（加载中）。图标与文字同时出现，不只靠颜色区分。
 */
import { computed } from 'vue'
import { CircleAlert, CircleCheck, Info, TriangleAlert } from '@lucide/vue'

const props = defineProps({
  kind: { type: String, default: 'info' },
})

const icon = computed(() => {
  const icons = { info: Info, warn: TriangleAlert, error: CircleAlert, good: CircleCheck }
  return icons[props.kind] || null
})
</script>

<template>
  <div class="notice" :class="kind" :role="kind === 'error' ? 'alert' : 'status'">
    <span v-if="kind === 'loading'" class="spinner" aria-hidden="true"></span>
    <component :is="icon" v-else-if="icon" :size="16" aria-hidden="true" />
    <div>
      <slot />
    </div>
  </div>
</template>
