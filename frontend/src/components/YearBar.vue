<script setup>
/*
 * 第一代城市研究页面共用的年份选择栏，可附带"导出北京小时数据"按钮。
 * 年份保存在 lib/state.js 中，切换页面时保持不变。
 */
import { computed } from 'vue'
import { Download } from '@lucide/vue'
import { apiHref } from '../lib/api'
import { historyYear } from '../lib/state'

const props = defineProps({
  years: { type: Array, default: () => [] },
  exportable: { type: Boolean, default: false },
  allowAll: { type: Boolean, default: true },
})

const year = computed({
  get: () => historyYear.value,
  set: value => {
    historyYear.value = value
  },
})

const sortedYears = computed(() => [...props.years].sort((a, b) => b - a))

// "全部年份"时导出最近一年，避免一次下载十一年的小时数据
const exportYear = computed(() => (year.value === 'all' ? '2025' : year.value))

const exportHref = computed(() => apiHref('export', {
  city: 'beijing',
  start: `${exportYear.value}-01-01`,
  end: `${exportYear.value}-12-31`,
}))
</script>

<template>
  <div class="year-bar">
    <label class="year-field">
      分析年份
      <select v-model="year" class="select" aria-label="分析年份">
        <option v-if="allowAll" value="all">2015—2025 全部</option>
        <option v-for="item in sortedYears" :key="item" :value="String(item)">{{ item }} 年</option>
      </select>
    </label>
    <slot />
    <a v-if="exportable" class="button small" :href="exportHref">
      <Download :size="14" />导出北京 {{ exportYear }} 年小时数据（CSV）
    </a>
  </div>
</template>

<style scoped>
.year-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
}

.year-field {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
}

.year-bar .button {
  margin-left: auto;
}
</style>
