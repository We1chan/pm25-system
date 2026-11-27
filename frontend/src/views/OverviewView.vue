<script setup>
/*
 * 区域概览页（第一代，2015—2025 城市小时均值）。
 * 数据：/api/meta（年份）、/api/overview（年度统计与城市相关）、/api/trend（城市浓度曲线）。
 * 城市均值会平滑单个站点的极值。
 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Database,
  TrendingUp,
} from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import Segmented from '../components/Segmented.vue'
import StatCard from '../components/StatCard.vue'
import YearBar from '../components/YearBar.vue'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { cityIds, cityNames } from '../lib/labels'
import { historyYear, loadHistoryMeta } from '../lib/state'
import {
  axisTime,
  baseOption,
  categoryAxis,
  cityColors,
  greenRamp,
  ink,
  lineSeries,
  timeAxis,
  timeTooltip,
  valueAxis,
  zoomControls,
} from '../lib/chart'

const meta = ref(null)
const overview = ref(null)
const trend = ref(null)
const error = ref('')

const period = ref('all')
const activeCities = ref(['beijing', 'tianjin', 'langfang'])

let overviewToken = 0
let trendToken = 0

// "全部年份"时，按年展开的视图使用最近一年
const concreteYear = computed(() => (historyYear.value === 'all' ? '2025' : historyYear.value))

const yearLabel = computed(() => {
  return historyYear.value === 'all' ? '2015—2025 年' : `${historyYear.value} 年`
})

const rising = computed(() => (overview.value?.yoy_percent ?? 0) > 0)

async function loadOverview() {
  const token = ++overviewToken
  try {
    const result = await api('overview', { year: historyYear.value })
    if (token === overviewToken) {
      overview.value = result
      error.value = ''
    }
  } catch (reason) {
    if (token === overviewToken) {
      error.value = reason.message
    }
  }
}

async function loadTrend() {
  if (!activeCities.value.length) {
    return
  }
  const token = ++trendToken
  const whole = period.value === 'all'
  try {
    const result = await api('trend', {
      cities: activeCities.value.join(','),
      start: whole ? '2015-01-01' : `${concreteYear.value}-01-01`,
      end: whole ? '2025-12-31' : `${concreteYear.value}-12-31`,
    })
    if (token === trendToken) {
      trend.value = result
    }
  } catch (reason) {
    error.value = reason.message
  }
}

onMounted(async () => {
  try {
    meta.value = await loadHistoryMeta()
  } catch (reason) {
    error.value = reason.message
  }
  await Promise.all([loadOverview(), loadTrend()])
})

watch(historyYear, () => {
  loadOverview()
  if (period.value !== 'all') {
    loadTrend()
  }
})

watch([period, activeCities], loadTrend, { deep: true })

function toggleCity(id) {
  if (activeCities.value.includes(id)) {
    // 至少保留一个城市，避免空图
    if (activeCities.value.length > 1) {
      activeCities.value = activeCities.value.filter(item => item !== id)
    }
  } else {
    activeCities.value = [...activeCities.value, id]
  }
}

// ---------- 图表 ----------

const trendOption = computed(() => {
  const series = trend.value?.series || []
  const monthly = trend.value?.resolution === 'month'
  const base = baseOption()
  // 上方的城市按钮带色块，已经起到图例作用，这里不再画 ECharts 图例
  return {
    ...base,
    grid: { ...base.grid, top: 34, bottom: 62 },
    tooltip: { ...base.tooltip, formatter: timeTooltip({ precision: monthly ? 'month' : 'day' }) },
    xAxis: timeAxis(),
    yAxis: valueAxis(monthly ? '月均 μg/m³' : '日均 μg/m³'),
    dataZoom: zoomControls(0),
    series: series.map(item => lineSeries({
      name: item.name,
      data: item.points.map(point => [axisTime(point.time), point.value]),
      color: cityColors[item.city_id],
      width: item.city_id === 'beijing' ? 2.5 : 1.5,
      z: item.city_id === 'beijing' ? 5 : 2,
    })),
  }
})

const matrixOption = computed(() => {
  const names = cityIds.map(id => cityNames[id])
  const cells = []
  for (const row of overview.value?.analysis?.city_correlations || []) {
    if (!Number.isFinite(row.correlation)) continue
    const a = cityIds.indexOf(row.city)
    const b = cityIds.indexOf(row.other)
    const value = Number(row.correlation.toFixed(3))
    // 深色格子上用白字，浅色格子上用深色字，保证文字可读
    const label = { color: value >= 0.75 ? '#fff' : ink.primary }
    cells.push({ value: [a, b, value], label })
    if (a !== b) {
      cells.push({ value: [b, a, value], label })
    }
  }
  if (!cells.length) return null
  return {
    textStyle: baseOption().textStyle,
    tooltip: {
      confine: true,
      formatter: item => {
        const [a, b, value] = item.value
        return `${names[a]} × ${names[b]}<br/>Pearson r = <b>${fmt(value, 3)}</b>`
      },
    },
    grid: { top: 8, left: 56, right: 12, bottom: 30 },
    xAxis: categoryAxis(names, { axisLine: { show: false }, axisLabel: { color: ink.secondary } }),
    // 纵轴倒序，使北京位于左上角，与横轴顺序对应
    yAxis: categoryAxis(names, {
      inverse: true,
      axisLine: { show: false },
      axisLabel: { color: ink.secondary },
    }),
    visualMap: { show: false, min: 0.3, max: 1, inRange: { color: greenRamp } },
    series: [{
      type: 'heatmap',
      data: cells,
      label: { show: true, fontSize: 12, formatter: item => fmt(item.value[2], 2) },
      itemStyle: { borderColor: '#fff', borderWidth: 3, borderRadius: 4 },
    }],
  }
})
</script>

<template>
  <div class="stack">
    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <Notice v-if="!overview && !error" kind="loading">正在读取区域观测…</Notice>

    <template v-if="overview">
      <YearBar :years="meta?.years || []" label="统计年份" exportable />
      <div class="stat-row three">
        <StatCard
          :label="`北京 PM₂.₅ 平均浓度 · ${yearLabel}`"
          :value="fmt(overview.beijing_mean)"
          unit="μg/m³"
          :icon="Activity"
          featured
        >
          <span v-if="overview.yoy_percent !== null" class="change" :class="{ up: rising }">
            <component :is="rising ? ArrowUpRight : ArrowDownRight" :size="13" />
            比上一年{{ rising ? '上升' : '下降' }} {{ fmt(Math.abs(overview.yoy_percent)) }}%
          </span>
          <span v-else>按有效观测小时计算</span>
        </StatCard>
        <StatCard
          label="北京最高小时浓度"
          :value="fmt(overview.beijing_max, 0)"
          unit="μg/m³"
          :icon="TrendingUp"
          :hint="`${yearLabel}内的城市均值小时最大值`"
        />
        <StatCard
          label="北京小时观测覆盖率"
          :value="fmt(overview.coverage * 100)"
          unit="%"
          :icon="Database"
        >
          <div class="meter"><i :style="{ width: `${overview.coverage * 100}%` }"></i></div>
          <span class="meter-caption">缺测小时保留为空，不做插值</span>
        </StatCard>
      </div>

      <PanelCard
        :title="period === 'all' ? '2015—2025 年月均浓度对比' : `${concreteYear} 年日均浓度对比`"
      >
        <template #actions>
          <Segmented
            v-model="period"
            label="时间范围"
            :options="[{ value: 'all', label: '十一年月均' }, { value: 'year', label: concreteYear + ' 年日均' }]"
          />
        </template>
        <div class="pills city-pills" role="group" aria-label="选择城市">
          <button
            v-for="id in cityIds"
            :key="id"
            type="button"
            :class="{ active: activeCities.includes(id) }"
            :aria-pressed="activeCities.includes(id)"
            @click="toggleCity(id)"
          >
            <i class="swatch" :style="{ background: cityColors[id] }"></i>{{ cityNames[id] }}
          </button>
        </div>
        <Chart :option="trendOption" height="320px" label="各城市 PM2.5 浓度变化" />
        <template #note>均值按有效观测小时计算；曲线中的空缺是缺测，可拖动底部时间条查看局部。</template>
      </PanelCard>

      <PanelCard
        title="六城浓度相关矩阵"
        note="使用 2015—2025 年全期数据。每对城市只统计两地同时有观测的小时，相关系数越接近 1 越同步。"
      >
        <template #actions>
          <span class="tag">2015—2025 全时段</span>
        </template>
        <Chart v-if="matrixOption" :option="matrixOption" height="340px" label="六城 PM2.5 小时浓度相关矩阵" />
        <Notice v-else>暂无六城浓度相关数据。</Notice>
      </PanelCard>

      <div class="observation-links">
        <a href="#analysis?tab=patterns">查看季节规律与气象关联 →</a>
      </div>
    </template>
  </div>
</template>

<style scoped>
.change {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--good);
  font-weight: 600;
}

.change.up {
  color: var(--danger);
}

.meter-caption {
  display: block;
  margin-top: 6px;
}

.city-pills {
  margin-bottom: 8px;
}

.observation-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  font-size: 13px;
}

</style>
