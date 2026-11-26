<script setup>
/*
 * 区域概览页（第一代，2015—2025 城市小时均值）。
 * 数据：/api/meta（城市坐标与年份）、/api/overview（年度统计与城市相关）、
 *       /api/snapshot（某一时刻六城浓度与北京气象）、/api/trend（城市浓度曲线）。
 * 城市均值会平滑单个站点的极值；气象为 ERA5 再分析资料。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Database,
  Droplets,
  Pause,
  Play,
  Thermometer,
  TrendingUp,
  Wind,
} from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import PmLegend from '../components/PmLegend.vue'
import Segmented from '../components/Segmented.vue'
import StatCard from '../components/StatCard.vue'
import YearBar from '../components/YearBar.vue'
import { api } from '../lib/api'
import { fmt, fmtPercent, isReplayOrigin } from '../lib/format'
import { cityIds, cityNames } from '../lib/labels'
import { historyYear, loadHistoryMeta } from '../lib/state'
import {
  axisTime,
  baseOption,
  cityColors,
  lineSeries,
  pointMapOption,
  timeAxis,
  timeTooltip,
  valueAxis,
  zoomControls,
} from '../lib/chart'

const meta = ref(null)
const overview = ref(null)
const snapshot = ref(null)
const trend = ref(null)
const error = ref('')

const snapshotDate = ref('2025-12-30')
const hour = ref(12)
const playing = ref(false)
const period = ref('all')
const activeCities = ref(['beijing', 'tianjin', 'langfang'])
const snapshotTime = computed(() => snapshotDate.value
  ? snapshotDate.value + 'T' + String(hour.value).padStart(2, '0') + ':00' : '')
const canReplaySnapshot = computed(() => Boolean(meta.value?.forecast_range)
  && isReplayOrigin(snapshotTime.value, meta.value.forecast_range))
const replayHref = computed(() => canReplaySnapshot.value
  ? '#forecast?tab=city&origin=' + encodeURIComponent(snapshotTime.value) : '#forecast?tab=city')

let playTimer = 0
let overviewToken = 0
let snapshotToken = 0
let trendToken = 0

// "全部年份"时，按年展开的视图使用最近一年
const concreteYear = computed(() => (historyYear.value === 'all' ? '2025' : historyYear.value))

const yearLabel = computed(() => {
  return historyYear.value === 'all' ? '2015—2025 年' : `${historyYear.value} 年`
})

const beijing = computed(() => snapshot.value?.cities.find(item => item.city_id === 'beijing'))

const ranking = computed(() => {
  const rows = [...(snapshot.value?.cities || [])]
  return rows.sort((a, b) => (b.pm25 ?? -1) - (a.pm25 ?? -1))
})

const rankingMax = computed(() => Math.max(100, ...ranking.value.map(item => item.pm25 ?? 0)))

// 排序条的长度；刻度至少到 100，避免浓度都很低时最短的城市也显得很长
function barWidth(value) {
  if (value === null || value === undefined) {
    return '0%'
  }
  return `${Math.max(2, (value / rankingMax.value) * 100)}%`
}

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

async function loadSnapshot() {
  const token = ++snapshotToken
  const time = snapshotTime.value
  if (!time) {
    snapshot.value = null
    return
  }
  try {
    const result = await api('snapshot', { time })
    if (token === snapshotToken) {
      snapshot.value = result
    }
  } catch (reason) {
    error.value = reason.message
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
  snapshotDate.value = `${concreteYear.value}-12-30`
  await Promise.all([loadOverview(), loadSnapshot(), loadTrend()])
})

watch(historyYear, () => {
  loadOverview()
  snapshotDate.value = `${concreteYear.value}-12-30`
  if (period.value !== 'all') {
    loadTrend()
  }
})

watch([snapshotDate, hour], loadSnapshot)
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

function togglePlay() {
  playing.value = !playing.value
  clearInterval(playTimer)
  if (playing.value) {
    playTimer = setInterval(() => {
      hour.value = (hour.value + 1) % 24
    }, 1500)
  }
}

onBeforeUnmount(() => clearInterval(playTimer))

// ---------- 图表 ----------

const mapOption = computed(() => {
  const cities = meta.value?.cities || []
  const points = (snapshot.value?.cities || []).map(item => {
    const place = cities.find(cityItem => cityItem.id === item.city_id)
    return {
      id: item.city_id,
      name: cityNames[item.city_id],
      lon: place?.longitude,
      lat: place?.latitude,
      value: item.pm25,
    }
  }).filter(point => point.lon !== undefined)
  return pointMapOption({
    points,
    center: [116.6, 39.75],
    zoom: 1.7,
    highlight: ['北京市'],
    labelAll: true,
    // 点的大小也随浓度变化，便于投影时远处看清
    sizeOf: point => 14 + Math.min(point.value ?? 0, 150) / 6,
  })
})

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

      <div class="grid-wide-left">
        <PanelCard title="指定时刻的六城浓度">
          <template #actions>
            <a :href="replayHref" class="button small">
              {{ canReplaySnapshot ? '从该时刻回放北京预测' : '查看北京城市均值回放' }}
            </a>
          </template>
          <div class="map-controls">
            <input
              v-model="snapshotDate"
              type="date"
              min="2015-01-01"
              max="2025-12-31"
              aria-label="观测日期"
            />
            <button
              class="button small"
              type="button"
              :aria-label="playing ? '暂停逐小时播放' : '逐小时播放'"
              @click="togglePlay"
            >
              <component :is="playing ? Pause : Play" :size="14" />{{ playing ? '暂停' : '播放' }}
            </button>
            <input
              v-model.number="hour"
              class="hour-slider"
              type="range"
              min="0"
              max="23"
              aria-label="观测小时"
            />
            <strong class="hour-label">{{ String(hour).padStart(2, '0') }}:00</strong>
          </div>
          <Chart :option="mapOption" height="360px" label="六城 PM2.5 浓度分布地图" />
          <PmLegend />
          <template #note>
            日期与小时只控制本图和右侧排序。点的大小与颜色表示城市小时均值。边界数据来自
            <a href="https://geo.datav.aliyun.com/" target="_blank" rel="noreferrer">DataV</a>。
          </template>
        </PanelCard>

        <PanelCard :title="snapshot ? `${snapshot.time.slice(0, 16)} 浓度排序` : '六城浓度排序'">
          <ol class="ranking">
            <li v-for="(item, index) in ranking" :key="item.city_id">
              <span class="rank">{{ index + 1 }}</span>
              <span class="rank-city">{{ cityNames[item.city_id] }}</span>
              <span class="rank-track">
                <i
                  :class="{ beijing: item.city_id === 'beijing' }"
                  :style="{ width: barWidth(item.pm25) }"
                ></i>
              </span>
              <strong class="num">{{ fmt(item.pm25, 0) }}</strong>
            </li>
          </ol>
          <div class="weather-strip">
            <div>
              <Thermometer :size="16" />
              <strong>{{ fmt(beijing?.temperature_2m) }} °C</strong>
              <span>北京气温</span>
            </div>
            <div>
              <Droplets :size="16" />
              <strong>{{ fmt(beijing?.relative_humidity_2m, 0) }}%</strong>
              <span>相对湿度</span>
            </div>
            <div>
              <Wind :size="16" />
              <strong>{{ fmt(beijing?.wind_speed_10m) }} m/s</strong>
              <span>风速</span>
            </div>
          </div>
          <template #note>单位 μg/m³。北京气象为 ERA5 再分析资料。</template>
        </PanelCard>
      </div>

      <div class="observation-links">
        <a href="#analysis?tab=patterns">查看季节规律与城市相关矩阵 →</a>
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

.map-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.map-controls input[type="date"] {
  min-height: 30px;
  padding: 0 8px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
}

.hour-slider {
  flex: 1 1 160px;
  accent-color: var(--brand);
}

.hour-label {
  min-width: 48px;
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}

.ranking {
  display: grid;
  gap: 12px;
  margin: 4px 0 18px;
  padding: 0;
  list-style: none;
}

.ranking li {
  display: grid;
  grid-template-columns: 22px 54px minmax(0, 1fr) 44px;
  align-items: center;
  gap: 10px;
  font-size: 14px;
}

.rank {
  font-size: 12px;
  color: var(--ink-3);
}

.rank-track {
  height: 10px;
  border-radius: 999px;
  background: var(--surface-sunken);
  overflow: hidden;
}

.rank-track i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: #a9b8ad;
}

.rank-track i.beijing {
  background: var(--brand);
}

.ranking strong {
  font-size: 16px;
}

.weather-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.weather-strip div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  font-size: 12px;
  color: var(--ink-3);
}

.weather-strip strong {
  font-size: 16px;
  color: var(--ink);
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
