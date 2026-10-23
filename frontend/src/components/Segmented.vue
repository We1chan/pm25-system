<script setup>
/*
 * 分段切换按钮，用于两三个互斥选项（如"2025 测试 / 2024 验证"）。
 * options: [{ value, label }]，用 v-model 绑定当前值。
 */
const model = defineModel({ type: [String, Number] })

defineProps({
  options: { type: Array, required: true },
  label: { type: String, default: '' },
})
</script>

<template>
  <div class="segmented" role="group" :aria-label="label">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      :class="{ active: model === option.value }"
      :aria-pressed="model === option.value"
      @click="model = option.value"
    >
      {{ option.label }}
    </button>
  </div>
</template>
