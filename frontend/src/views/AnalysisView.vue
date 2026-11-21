<script setup>
/*
 * 时空分析页（第一代，2015—2025 城市小时均值）。
 * 数据：/api/pattern（月份 × 小时平均与四季平均）、/api/weather（气象与浓度散点及相关系数）、
 *       /api/overview（城市间相关矩阵）。
 * 散点图为了绘图速度按时间等距抽样，相关系数用全部有效小时计算。相关不代表因果。
 */
import { computed, onMounted, ref, watch } from 'vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import YearBar from '../components/YearBar.vue'
import { api } from '../lib/api'
import { fmt, fmtInt } from '../lib/format'
import { cityIds, cityNames } from '../lib/labels'
import { historyYear, loadHistoryMeta } from '../lib/state'
import {
  barSeries,
  baseOption,
  categoryAxis,
  categoryTooltip,
  cityColors,
  greenRamp,
  ink,
  valueAxis,
} from '../lib/chart'

const weatherOptions = {
  relative_humidity_2m: { name: '相对湿度', unit: '%' },
  wind_speed_10m: { name: '风速', unit: 'm/s' },
  temperature_2m: { name: '气温', unit: '°C' },
}

const meta = ref(null)
const city = ref('beijing')
const variable = ref('relative_humidity_2m')
const pattern = ref(null)
const weather = ref(null)
const analysis = ref(null)
const error = ref('')
const busy = ref(true)

let request = 0

async function load() {
  const token = ++request
  busy.value = true
  error.value = ''
  const year = historyYear.value
  try {
    const [patternResult, weatherResult, overviewResult] = await Promise.all([
      api('pattern', { city: city.value, year }),
      api('weather', { city: city.value, year, variable: variable.value }),
      api('overview', { year }),
    ])
    if (token === request) {
      pattern.value = patternResult
      weather.value = weatherResult
      analysis.value = overviewResult.analysis
    }
  } catch (reason) {
    if (token === request) {
      error.value = reason.message
    }
  } finally {
    if (token === request) {
      busy.value = false
    }
  }
}

onMounted(async () => {
  loadHistoryMeta().then(result => {
    meta.value = result
  }).catch(reason => {
    error.value = reason.message
  })
  await load()
})

watch([city, variable, historyYear], load)

// ---------- 图表 ----------

const heatOption = computed(() => {
  const cells = (pattern.value?.cells || []).filter(cell => cell.value !== null)
  const max = Math.max(60, ...cells.map(cell => cell.value))
  return {
    textStyle: baseOption().textStyle,
    tooltip: {
      confine: true,
      formatter: item => {
        const [hour, month, value] = item.value
        return `${month + 1} 月 · ${hour}:00<br/>平均 PM₂.₅ <b>${fmt(value)}</b> μg/m³`
      },
    },
    grid: { top: 8, left: 44, right: 12, bottom: 64 },
    xAxis: categoryAxis(Array.from({ length: 24 }, (_, index) => index), {
      name: '时',
      axisLine: { show: false },
      axisLabel: { color: ink.muted, fontSize: 11, interval: 2 },
    }),
    yAxis: categoryAxis(Array.from({ length: 12 }, (_, index) => `${index + 1} 月`), {
      axisLine: { show: false },
    }),
    visualMap: {
      min: 0,
      max: Math.ceil(max),
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 12,
      itemHeight: 180,
      text: ['高', '低'],
      textStyle: { color: ink.muted, fontSize: 11 },
      inRange: { color: greenRamp },
    },
    series: [{
      type: 'heatmap',
      data: cells.map(cell => [cell.hour, cell.month - 1, Number(cell.value.toFixed(1))]),
      itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 3 },
      emphasis: { itemStyle: { borderColor: ink.primary, borderWidth: 1 } },
    }],
  }
})

const seasonOrder = ['春季', '夏季', '秋季', '冬季']

const seasonOption = computed(() => {
  const values = seasonOrder.map(name => {
    return pattern.value?.seasons.find(item => item.season === name)?.value ?? null
  })
  const base = baseOption()
  return {
    ...base,
    grid: { ...base.grid, top: 34 },
    tooltip: { ...base.tooltip, formatter: categoryTooltip() },
    xAxis: categoryAxis(seasonOrder, { axisLabel: { color: ink.secondary, fontSize: 13 } }),
    yAxis: valueAxis(),
    series: [barSeries({
      name: '平均 PM₂.₅',
      data: values,
      color: cityColors[city.value],
      width: 48,
      labels: true,
      digits: 1,
    })],
  }
})

const scatterOption = computed(() => {
  const info = weatherOptions[variable.value]
  const base = baseOption()
  return {
    ...base,
    grid: { ...base.grid, top: 34, bottom: 40 },
    tooltip: {
      ...base.tooltip,
      trigger: 'item',
      formatter: item => {
        const [x, y, time] = item.data
        const weatherText = `${info.name} ${fmt(x)} ${info.unit}`
        return `${time.slice(0, 16)}<br/>${weatherText}<br/>PM₂.₅ ${fmt(y)} μg/m³`
      },
    },
    xAxis: valueAxis(`${info.name} ${info.unit}`, {
      nameLocation: 'middle',
      nameGap: 26,
      nameTextStyle: { color: ink.muted, fontSize: 11 },
      scale: true,
      splitLine: { show: false },
      axisLine: { show: true, lineStyle: { color: ink.axis } },
    }),
    yAxis: valueAxis(),
    series: [{
      type: 'scatter',
      symbolSize: 5,
      itemStyle: { color: cityColors[city.value], opacity: 0.28 },
      data: (weather.value?.points || []).map(point => [point.x, point.y, point.ts]),
    }],
  }
})

const matrixOption = computed(() => {
  const names = cityIds.map(id => cityNames[id])
  const cells = []
  for (const row of analysis.value?.city_correlations || []) {
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
    <YearBar :years="meta?.years || []">
      <div class="pills" role="group" aria-label="选择城市">
        <button
          v-for="id in cityIds"
          :key="id"
          type="button"
          :class="{ active: city === id }"
          :aria-pressed="city === id"
          @click="city = id"
        >
          <i class="swatch" :style="{ background: cityColors[id] }"></i>{{ cityNames[id] }}
        </button>
      </div>
    </YearBar>

    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <Notice v-if="busy && !pattern" kind="loading">正在计算分析视图…</Notice>

    <template v-if="pattern">
      <div class="grid-wide-left">
        <PanelCard
          :title="`${cityNames[city]}各月各小时平均浓度`"
          note="每格为该月该小时全部有效观测的平均浓度（μg/m³），颜色越深浓度越高。"
        >
          <Chart :option="heatOption" height="360px" label="月份与小时的 PM2.5 平均浓度热力图" />
        </PanelCard>
        <PanelCard
          :title="`${cityNames[city]}四季平均浓度`"
          note="按日历月份分季：春 3—5 月，夏 6—8 月，秋 9—11 月，冬 12—2 月。"
        >
          <Chart :option="seasonOption" height="360px" label="四季 PM2.5 平均浓度" />
        </PanelCard>
      </div>

      <div class="grid-2">
        <PanelCard :title="`${cityNames[city]}：${weatherOptions[variable].name}与 PM₂.₅ 的关联`">
          <template #actions>
            <select v-model="variable" class="select" aria-label="选择气象变量">
              <option v-for="(info, key) in weatherOptions" :key="key" :value="key">
                {{ info.name }}
              </option>
            </select>
          </template>
          <div class="correlation">
            <span>Pearson 相关系数</span>
            <strong>{{ fmt(weather?.correlation, 3) }}</strong>
            <span>基于 {{ fmtInt(weather?.n) }} 个有效小时；图中按时间等距抽样显示</span>
          </div>
          <Chart :option="scatterOption" height="300px" label="气象变量与 PM2.5 散点图" />
          <template #note>相关不代表因果；气象为 ERA5 历史再分析资料。</template>
        </PanelCard>
        <PanelCard
          title="六城浓度相关矩阵"
          note="使用 2015—2025 年全期数据。每对城市只统计两地同时有观测的小时，相关系数越接近 1 越同步。"
        >
          <template #actions>
            <span class="tag">2015—2025 全时段</span>
          </template>
          <Chart :option="matrixOption" height="340px" label="六城 PM2.5 小时浓度相关矩阵" />
        </PanelCard>
      </div>
    </template>
  </div>
</template>

<style scoped>
.correlation {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--ink-3);
}

.correlation strong {
  font-size: 22px;
  color: var(--ink);
}
</style>
