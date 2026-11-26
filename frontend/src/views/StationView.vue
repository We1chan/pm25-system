<script setup>
/*
 * 站点与 GPU 页（第二代，2022—2025 历史数据）。
 * 数据：/api/stations/meta、/api/stations/models（模型登记与 GPU 训练证据）、
 *       /api/stations/snapshot、/history、/trend、/forecast（所选站点与时刻）。
 * 页面读取已训练模型的批量预测结果。
 * 模型比较只在同一批有效站点小时上进行；推荐模型只看 2024 年北京站点验证集 RMSE。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Cpu, Download, Info, Timer } from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import PmLegend from '../components/PmLegend.vue'
import Segmented from '../components/Segmented.vue'
import { api } from '../lib/api'
import { bjFull, fmt, fmtDuration, fmtInt, isReplayOrigin } from '../lib/format'
import { cityIds, cityNames, stationModelNames, weatherVariables } from '../lib/labels'
import {
  axisTime,
  barSeries,
  baseOption,
  categoryAxis,
  categoryTooltip,
  ink,
  legend,
  lineSeries,
  modelColors,
  palette,
  pointMapOption,
  roleColors,
  timeAxis,
  timeTooltip,
  valueAxis,
  zoomControls,
} from '../lib/chart'

const meta = ref(null)
const registry = ref(null)
const error = ref('')
const forecastError = ref('')
const observationError = ref('')
const trendError = ref('')
const busy = ref(false)

const city = ref('beijing')
const props = defineProps({ section: { type: String, required: true } })

const stationId = ref('1001A')
const time = ref('2025-12-30T12:00')
const model = ref('best')
const year = ref('2025')
const weatherVar = ref('wind_speed_10m')
const split = ref('test')
const scope = ref('beijing')

const snapshot = ref(null)
const history = ref(null)
const trend = ref(null)
const forecast = ref(null)

let setupTimer = 0

const stations = computed(() => {
  const all = meta.value?.stations || []
  return all.filter(item => city.value === 'all' || item.city_id === city.value)
})

const replayReady = computed(() => props.section === 'replay' && Boolean(meta.value?.ready))
const validTime = computed(() => isReplayOrigin(time.value, meta.value?.forecast_range || []))

const yearOptions = ['2025', '2024', '2023', '2022']
const scopeOptions = [
  { value: 'beijing', label: '北京站点' },
  { value: 'all', label: '六城站点' },
]
const splitOptions = [
  { value: 'test', label: '2025 测试' },
  { value: 'validation', label: '2024 验证' },
]

const gpu = computed(() => registry.value?.gpu || null)

const runs = computed(() => Object.values(registry.value?.runs || {}))

const preparationText = computed(() => {
  const phases = {
    spark_prepare: 'Spark 清洗、融合与 72 小时特征构建',
    spark_rf: 'Spark 随机森林训练与评估',
    cuda_training: 'CUDA 时序模型训练',
    publishing: '正在生成站点观测与预测查询索引',
    complete: '已完成',
  }
  return phases[meta.value?.training?.phase] || 'HDFS 原始数据入库'
})

// 同一批样本上的评估指标；variant 为空时排除"只用当前气象"的消融实验
function metric(modelId, horizon, variant) {
  const run = runs.value.find(item => {
    if (item.model !== modelId || item.horizon !== horizon) {
      return false
    }
    return variant ? item.variant === variant : item.variant !== 'instant_weather'
  })
  return run?.metrics.find(item => item.split === split.value && item.scope === scope.value)
}

// ---------- 数据加载 ----------

async function setup() {
  try {
    const [stationMeta, models] = await Promise.all([
      api('stations/meta'),
      props.section === 'replay' ? null : api('stations/models'),
    ])
    if (props.section === 'replay' && stationMeta.ready && !meta.value?.ready) {
      time.value = stationMeta.default_origin || time.value
    }
    meta.value = stationMeta
    registry.value = models
    error.value = ''
  } catch (reason) {
    error.value = reason.message
  }
}

async function loadForecast([ready, id, origin, requestedModel], _previous, onCleanup) {
  let active = true
  onCleanup(() => { active = false })
  forecastError.value = ''
  if (!ready || !id || !validTime.value) {
    busy.value = false
    forecast.value = null
    return
  }

  busy.value = true
  try {
    const next = await api('stations/forecast', { station_id: id, time: origin, model: requestedModel })
    if (active) forecast.value = next
  } catch (reason) {
    if (active) {
      forecast.value = null
      forecastError.value = reason.message
    }
  } finally {
    if (active) busy.value = false
  }
}

async function loadObservations([ready, cityId, id, origin], _previous, onCleanup) {
  let active = true
  onCleanup(() => { active = false })
  snapshot.value = null
  history.value = null
  observationError.value = ''
  if (!ready || !id || !validTime.value) return

  const [observations, past] = await Promise.allSettled([
    api('stations/snapshot', { time: origin, city: cityId }),
    api('stations/history', { station_id: id, end: origin, hours: 72 }),
  ])
  if (!active) return
  snapshot.value = observations.value || null
  history.value = past.value || null
  observationError.value = observations.reason?.message || past.reason?.message || ''
}

async function loadTrend([ready, id, selectedYear], _previous, onCleanup) {
  let active = true
  onCleanup(() => { active = false })
  trend.value = null
  trendError.value = ''
  if (!ready || !id) return
  try {
    const next = await api('stations/trend', { station_id: id, year: selectedYear })
    if (active) trend.value = next
  } catch (reason) {
    if (active) trendError.value = reason.message
  }
}

onMounted(() => {
  setup()
  // 流水线未完成时每 15 秒检查一次进度。
  setupTimer = setInterval(() => {
    if (!meta.value?.ready) setup()
  }, 15000)
})
onBeforeUnmount(() => clearInterval(setupTimer))

watch(stations, items => {
  if (!items.some(item => item.station_id === stationId.value)) {
    stationId.value = items[0]?.station_id || ''
  }
})
watch([replayReady, stationId, time, model], loadForecast)
watch([replayReady, city, stationId, time], loadObservations)
watch([replayReady, stationId, year], loadTrend)

function onMapSelect(event) {
  if (event.data?.id) {
    stationId.value = event.data.id
  }
}

// 把当前回放结果导出为 CSV（带 BOM，Excel 可直接打开中文）
function downloadCsv() {
  const result = forecast.value
  if (!result || busy.value) return
  const header = ['站点', '预测起点', '目标时刻', '提前小时', 'Spark随机森林', 'CUDA TCN', '真实值', '持续性基线', '选用模型', '预测PM2.5']
  const rows = result.points.map(point => [
    result.station.station_id,
    point.origin,
    point.target,
    point.horizon,
    point.rf,
    point.tcn72,
    point.actual ?? '',
    point.baseline,
    stationModelNames[point.model],
    point.prediction,
  ])
  const text = '﻿' + [header, ...rows].map(row => row.join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `station_${result.station.station_id}_forecast.csv`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ---------- 图表 ----------

const rankingRows = computed(() => {
  const rows = [...(snapshot.value?.stations || [])]
  return rows.sort((a, b) => (b.pm25 ?? -1) - (a.pm25 ?? -1))
})

const mapOption = computed(() => {
  const points = (snapshot.value?.stations || [])
    .filter(item => item.longitude !== null && item.latitude !== null)
    .map(item => ({
      id: item.station_id,
      name: `${item.name}（${item.station_id}）`,
      lon: item.longitude,
      lat: item.latitude,
      value: item.pm25,
    }))
  // 以站点的平均位置为中心，按站点分布范围估计缩放
  const lons = points.map(point => point.lon)
  const lats = points.map(point => point.lat)
  const center = lons.length
    ? [(Math.min(...lons) + Math.max(...lons)) / 2, (Math.min(...lats) + Math.max(...lats)) / 2]
    : [116.4, 39.9]
  const span = lons.length ? Math.max(Math.max(...lons) - Math.min(...lons), 0.3) : 4
  const zoom = Math.min(9, Math.max(1, 6.4 / (span * 1.6)))
  const highlight = city.value === 'all' ? [] : [`${cityNames[city.value]}市`]
  return pointMapOption({ points, selectedId: stationId.value, center, zoom, highlight })
})

const forecastOption = computed(() => {
  const result = forecast.value
  if (!result) {
    return null
  }
  const origin = axisTime(result.origin)
  const start = [origin, result.current]
  const series = (key, name, color, extra = {}) => lineSeries({
    name,
    data: [start, ...result.points.map(point => [axisTime(point.target), point[key]])],
    color,
    points: true,
    ...extra,
  })
  const curves = [
    lineSeries({
      name: '历史观测',
      data: result.history.map(point => [axisTime(point.ts), point.pm25]),
      color: roleColors.observed,
    }),
    series('prediction', '模型预测', modelColors[result.points[0]?.model] || palette.green, { width: 2.5, z: 4 }),
    series('actual', '后续真实值', roleColors.observed, { dashed: true, z: 5 }),
  ]
  if (result.model !== 'persistence') {
    curves.push(series('baseline', '持续性基线', roleColors.baseline, { dashed: true, points: false }))
  }
  const base = baseOption()
  return {
    ...base,
    animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    legend: legend(curves.map(curve => curve.name)),
    grid: { ...base.grid, bottom: 62 },
    tooltip: { ...base.tooltip, formatter: timeTooltip() },
    xAxis: timeAxis(),
    yAxis: valueAxis(),
    dataZoom: zoomControls(55),
    series: curves,
  }
})

const weatherOption = computed(() => {
  const key = weatherVar.value
  const variable = weatherVariables[key]
  const data = (history.value?.points || []).map(point => [axisTime(point.ts), point[key]])
  const base = baseOption()
  const isRain = key === 'precipitation'
  return {
    ...base,
    grid: { ...base.grid, top: 34 },
    tooltip: { ...base.tooltip, formatter: timeTooltip({ unit: variable.unit }) },
    xAxis: timeAxis(),
    yAxis: valueAxis(variable.unit, { scale: !isRain }),
    series: [
      isRain
        ? barSeries({ name: variable.name, data, color: palette.blue, width: 6 })
        : lineSeries({ name: variable.name, data, color: palette.blue }),
    ],
  }
})

const trendOption = computed(() => {
  const data = (trend.value?.points || []).map(point => [axisTime(point.date), point.pm25])
  const base = baseOption()
  return {
    ...base,
    grid: { ...base.grid, top: 34 },
    tooltip: { ...base.tooltip, formatter: timeTooltip({ precision: 'day' }) },
    xAxis: timeAxis(),
    yAxis: valueAxis('日均 μg/m³'),
    series: [lineSeries({ name: '日均 PM₂.₅', data, color: roleColors.observed, width: 1.5 })],
  }
})

const horizons = [1, 2, 3, 4, 5, 6]

const errorOption = computed(() => {
  const ids = ['tcn72', 'rf', 'persistence']
  const base = baseOption()
  return {
    ...base,
    legend: legend(ids.map(id => stationModelNames[id])),
    tooltip: { ...base.tooltip, formatter: categoryTooltip({ digits: 2 }) },
    xAxis: categoryAxis(horizons.map(h => `+${h} h`)),
    yAxis: valueAxis('RMSE μg/m³'),
    series: ids.map(id => lineSeries({
      name: stationModelNames[id],
      data: horizons.map(h => metric(id, h)?.rmse ?? null),
      color: modelColors[id],
      width: id === 'tcn72' ? 2.5 : 2,
      dashed: id === 'persistence',
      points: true,
    })),
  }
})

const ablationOption = computed(() => {
  const bars = [
    { label: 'RF · 只用当前气象', value: metric('rf', 6, 'instant_weather')?.rmse, color: '#86b6ef' },
    { label: 'RF · 72 小时气象历史', value: metric('rf', 6, 'history72')?.rmse, color: palette.blue },
    { label: 'TCN · 72 小时完整序列', value: metric('tcn72', 6)?.rmse, color: palette.green },
  ]
  const base = baseOption()
  return {
    ...base,
    grid: { ...base.grid, top: 34 },
    tooltip: { ...base.tooltip, formatter: categoryTooltip({ digits: 2 }) },
    xAxis: categoryAxis(bars.map(bar => bar.label), {
      axisLabel: { color: ink.secondary, fontSize: 12, interval: 0 },
    }),
    yAxis: valueAxis('+6 h RMSE μg/m³'),
    series: [
      barSeries({
        name: '+6 h RMSE',
        data: bars.map(bar => ({ value: bar.value ?? null, itemStyle: { color: bar.color } })),
        color: palette.blue,
        width: 44,
        labels: true,
      }),
    ],
  }
})

const trainingOption = computed(() => {
  const epochs = gpu.value?.epochs || []
  const bestIndex = epochs.findIndex(item => item.epoch === gpu.value?.best_epoch)
  const bestValue = epochs[bestIndex]?.validation_beijing_h6_rmse
  const base = baseOption()
  return {
    ...base,
    grid: { ...base.grid, top: 34 },
    tooltip: {
      ...base.tooltip,
      formatter: categoryTooltip({ digits: 2, title: label => `第 ${label} 轮` }),
    },
    xAxis: categoryAxis(epochs.map(item => item.epoch), { name: '训练轮次' }),
    // 各轮误差差别不大，纵轴不从 0 开始才看得出变化
    yAxis: valueAxis('验证集 +6 h RMSE', { scale: true }),
    series: [
      lineSeries({
        name: '验证集 +6 h RMSE',
        data: epochs.map(item => ({
          value: item.validation_beijing_h6_rmse,
          symbolSize: item.epoch === gpu.value.best_epoch ? 12 : 8,
        })),
        color: palette.green,
        points: true,
        // 标出保存为最终模型的那一轮（验证集误差最低）
        markPoint: bestIndex < 0 ? undefined : {
          symbol: 'pin',
          symbolSize: 40,
          itemStyle: { color: palette.green },
          label: { formatter: '最佳', fontSize: 10, color: '#fff' },
          data: [{ coord: [bestIndex, bestValue] }],
        },
      }),
    ],
  }
})
</script>

<template>
  <div class="stack">
    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <Notice v-if="!meta && !error" kind="loading">正在连接站点实验数据…</Notice>

    <PanelCard v-else-if="meta && !meta.ready" title="站点数据与 GPU 模型正在准备">
      <p class="panel-text">全国逐站小时原始记录 → Spark 清洗与 72 小时特征 → CPU / CUDA 模型 → 同条件独立评估。</p>
      <p class="panel-text">
        已下载 {{ fmtInt(meta.download?.hourly_files) }} 份原始小时文件。当前阶段：{{ preparationText }}。
      </p>
    </PanelCard>

    <template v-if="meta?.ready">
      <template v-if="section === 'replay'">
        <PanelCard title="选择站点、预测起点与模型">
          <div class="toolbar">
            <label class="field">
              城市
              <select v-model="city">
                <option value="all">全部六城</option>
                <option v-for="id in cityIds" :key="id" :value="id">{{ cityNames[id] }}</option>
              </select>
            </label>
            <label class="field wide">
              监测站点
              <select v-model="stationId" :disabled="!stations.length">
                <option v-for="item in stations" :key="item.station_id" :value="item.station_id">
                  {{ item.name }}（{{ item.station_id }}）
                </option>
              </select>
            </label>
            <label class="field">
              预测起点（北京时间）
              <input
                v-model.lazy="time"
                type="datetime-local"
                :min="meta.forecast_range?.[0]"
                :max="meta.forecast_range?.[1]"
                step="3600"
              />
            </label>
            <label class="field">
              预测模型
              <select v-model="model">
                <option v-for="(name, id) in stationModelNames" :key="id" :value="id">
                  {{ name }}
                </option>
              </select>
            </label>
          </div>
          <template #note>
            选择站点、起点或模型后自动更新。可回放 2024 年验证期和 2025 年测试期的整点。
        </template>
        </PanelCard>

        <Notice v-if="!stationId">该城市暂无可回放的监测站，可切换城市。</Notice>
        <Notice v-else-if="!validTime" kind="warn">请选择可用日期范围内的整点。</Notice>
        <Notice v-if="busy && !forecast" kind="loading">正在读取站点回放结果…</Notice>

        <template v-if="stationId && validTime">
          <Notice v-if="forecastError" kind="error">{{ forecastError }}</Notice>

          <PanelCard
            v-if="forecast"
            :title="`${forecast.station.name || forecast.station.station_id} · 六小时预测与实测`"
          >
            <template #actions>
              <span class="tag">{{ stationModelNames[forecast.model] }} · 起点 {{ bjFull(forecast.origin) }}</span>
              <span class="replay-loading" role="status">
                <template v-if="busy">
                  <span class="spinner" aria-hidden="true"></span>
                  正在读取
                </template>
              </span>
              <button class="button small" type="button" :disabled="busy" @click="downloadCsv">
                <Download :size="14" />导出 CSV
              </button>
            </template>
            <Chart :option="forecastOption" :aria-busy="busy" height="330px" label="站点六小时预测、实测与基线" />
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>目标时刻</th>
                    <th>选用模型</th>
                    <th class="num">预测值</th>
                    <th class="num">真实值</th>
                    <th class="num">持续性基线</th>
                    <th class="num">随机森林参考</th>
                    <th class="num">TCN 参考</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="point in forecast.points" :key="point.horizon">
                    <td>
                      {{ bjFull(point.target) }} <span class="tag">+{{ point.horizon }} h</span>
                    </td>
                    <td>{{ stationModelNames[point.model] }}</td>
                    <td class="num strong">{{ fmt(point.prediction) }}</td>
                    <td class="num">{{ fmt(point.actual) }}</td>
                    <td class="num">{{ fmt(point.baseline) }}</td>
                    <td class="num">{{ fmt(point.rf) }}</td>
                    <td class="num">{{ fmt(point.tcn72) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <template #note>
              {{ forecast.split === 'test' ? '2025 年独立测试期：未参与模型选择。' : '2024 年验证期：用于选择推荐模型。' }}
              页面读取真实模型的批量输出；缺失的真实值不参与误差计算。
            </template>
          </PanelCard>

          <Notice v-if="observationError" kind="error">{{ observationError }}</Notice>
          <div class="grid-wide-left">
            <PanelCard
              kicker="站点观测 · 点击站点切换"
              :title="snapshot ? bjFull(snapshot.time) + ' 各站点浓度' : '站点浓度地图'"
              note="可缩放拖动；只显示该时刻有坐标的站点，灰色表示无实测。"
            >
              <Chart :option="mapOption" height="360px" label="监测站点 PM2.5 地图" @select="onMapSelect" />
              <PmLegend />
            </PanelCard>
            <PanelCard
              kicker="站点对比"
              :title="`${city === 'all' ? '六城' : cityNames[city]}站点浓度排序`"
              note="缺测保留为空；站点停运或尚未启用的时段也没有观测。"
            >
              <div class="table-wrap tall">
                <table>
                  <thead>
                    <tr>
                      <th>站点</th>
                      <th class="num">PM₂.₅ μg/m³</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="item in rankingRows"
                      :key="item.station_id"
                      :class="{ selected: item.station_id === stationId }"
                    >
                      <td>
                        <button class="button small ghost station-pick" type="button"
                          :aria-pressed="item.station_id === stationId" @click="stationId = item.station_id">
                          {{ item.name }} <span class="muted">{{ item.station_id }}</span>
                        </button>
                      </td>
                      <td class="num strong">{{ fmt(item.pm25) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </PanelCard>
          </div>

          <div class="grid-2">
            <PanelCard
              kicker="模型输入"
              title="预测起点之前 72 小时的天气"
              note="ERA5 再分析资料，取城市代表坐标，同城站点共享；不是空气站的气象实测。"
            >
              <template #actions>
                <select v-model="weatherVar" class="select" aria-label="选择气象变量">
                  <option v-for="(variable, key) in weatherVariables" :key="key" :value="key">
                    {{ variable.name }}
                  </option>
                </select>
              </template>
              <Chart :option="weatherOption" height="250px" label="预测起点之前 72 小时天气" />
            </PanelCard>
            <PanelCard
              kicker="站点逐日"
              :title="trend ? (trend.station.name || trend.station.station_id) + ' · ' + trend.year + ' 年日均浓度' : '站点日均浓度'"
              note="按有效小时计算日均值；全天无观测时保留空缺。"
            >
              <template #actions>
                <select v-model="year" class="select" aria-label="选择日均趋势年份">
                  <option v-for="item in yearOptions" :key="item" :value="item">{{ item }} 年</option>
                </select>
              </template>
              <Notice v-if="trendError" kind="error">{{ trendError }}</Notice>
              <Chart v-else :option="trendOption" height="250px" label="所选站点日均 PM2.5" />
            </PanelCard>
          </div>
        </template>

      </template>

      <PanelCard v-if="section === 'evaluation'" kicker="同一批样本上的比较" title="TCN、随机森林与持续性基线">
        <template #actions>
          <Segmented v-model="scope" label="评估范围" :options="scopeOptions" />
          <Segmented v-model="split" label="评估期间" :options="splitOptions" />
        </template>
        <div class="grid-2">
          <div>
            <h3 class="sub-title">各提前小时的 RMSE</h3>
            <Chart :option="errorOption" height="290px" label="各模型各提前小时 RMSE" />
          </div>
          <div>
            <h3 class="sub-title">天气信息怎么用：+6 小时消融对比</h3>
            <Chart :option="ablationOption" height="290px" label="三种输入方式的六小时 RMSE" />
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>提前</th>
                <th>模型</th>
                <th class="num">MAE</th>
                <th class="num">RMSE</th>
                <th class="num">R²</th>
                <th class="num">有效样本</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="h in [1, 3, 6]" :key="h">
                <tr v-for="id in ['tcn72', 'rf', 'persistence']" :key="`${h}-${id}`">
                  <td>+{{ h }} h</td>
                  <td>
                    <i class="swatch" :style="{ background: modelColors[id] }"></i>
                    {{ stationModelNames[id] }}
                  </td>
                  <td class="num">{{ fmt(metric(id, h)?.mae, 2) }}</td>
                  <td class="num strong">{{ fmt(metric(id, h)?.rmse, 2) }}</td>
                  <td class="num">{{ fmt(metric(id, h)?.r2, 3) }}</td>
                  <td class="num">{{ fmtInt(metric(id, h)?.n) }}</td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <template #note>
          每个提前小时内三种方法使用完全相同的有效样本。推荐模型只看 2024 年北京站点验证集 RMSE；
          随机森林读取 {{ meta.summary.feature_count }} 列滞后与滚动摘要特征，TCN 直接读取 72 小时完整序列。
        </template>
      </PanelCard>

      <Notice v-if="section === 'training' && !gpu">CUDA 训练记录尚未就绪。</Notice>
      <PanelCard v-if="section === 'training' && gpu" title="训练指标与验证误差">
        <template #actions>
          <span class="tag brand"><Cpu :size="13" />{{ gpu.device }}</span>
        </template>
        <div class="gpu-grid">
          <dl class="facts">
            <div>
              <dt>真实训练起点</dt>
              <dd>{{ fmtInt(gpu.train_origins) }}</dd>
            </div>
            <div>
              <dt>PyTorch 峰值显存</dt>
              <dd>{{ fmt(gpu.peak_torch_memory_mib, 0) }} MiB</dd>
            </div>
            <div>
              <dt>最佳 / 实际训练轮次</dt>
              <dd>{{ gpu.best_epoch }} / {{ gpu.epochs.length }}</dd>
            </div>
            <div>
              <dt><Timer :size="13" /> 训练及推理耗时</dt>
              <dd>{{ fmtDuration(gpu.elapsed_seconds) }}</dd>
            </div>
          </dl>
          <Chart :option="trainingOption" height="250px" label="各训练轮次的验证集六小时 RMSE" />
        </div>
        <template #note>
          PyTorch {{ gpu.pytorch }} · CUDA {{ gpu.cuda_runtime }} · 随机种子 {{ gpu.seed }}。
          显存与利用率是训练时实际采样的值；训练结束后显卡空闲。验证集误差最低的一轮被保存为最终模型。
        </template>
      </PanelCard>

      <div v-if="section === 'replay'" class="method-note">
        <Info :size="16" aria-hidden="true" />
        <p>
          Spark 从全国档案中提取六城站点，去重并构建完整小时网格，保留历史站点身份；
          天气历史和区域污染信息只取预测起点及之前。历史再分析回测不能代表真实在线预报表现。
          <a :href="meta.summary.archive_repository" target="_blank" rel="noreferrer">查看归档来源</a>
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.toolbar .field.wide {
  flex-basis: 220px;
}

.button.station-pick {
  justify-content: flex-start;
  text-align: left;
  white-space: normal;
}

.sub-title {
  margin-bottom: 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-2);
}

.gpu-grid {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(0, 2fr);
  gap: 24px;
  align-items: center;
}

.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 0;
}

.facts div {
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  border: 1px solid var(--border);
}

.facts dt {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--ink-3);
}

.facts dd {
  margin: 2px 0 0;
  font-size: 20px;
  font-weight: 650;
}

td .swatch {
  margin-right: 6px;
  vertical-align: -1px;
}

@media (max-width: 1180px) {
  .gpu-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
