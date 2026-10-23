<script setup>
/*
 * 站点与 GPU 页（第二代，2022—2025 历史数据）。
 * 数据：/api/stations/meta、/api/stations/models（模型登记与 GPU 训练证据）、
 *       /api/stations/snapshot、/history、/trend、/forecast（所选站点与时刻）。
 * 页面只读取已训练模型的批量预测结果，点击按钮不会重新训练。
 * 模型比较只在同一批有效站点小时上进行；推荐模型只看 2024 年北京站点验证集 RMSE。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Cpu, Database, Download, Info, ScanLine, Timer } from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import PmLegend from '../components/PmLegend.vue'
import Segmented from '../components/Segmented.vue'
import StatCard from '../components/StatCard.vue'
import { api } from '../lib/api'
import { bjFull, fmt, fmtBytes, fmtDuration, fmtInt } from '../lib/format'
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
const busy = ref(false)

const city = ref('beijing')
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

let request = 0
let setupTimer = 0

const stations = computed(() => {
  const all = meta.value?.stations || []
  return all.filter(item => city.value === 'all' || item.city_id === city.value)
})

const selected = computed(() => {
  return meta.value?.stations.find(item => item.station_id === stationId.value)
})

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
    const [stationMeta, models] = await Promise.all([api('stations/meta'), api('stations/models')])
    meta.value = stationMeta
    registry.value = models
    if (stationMeta.ready && !snapshot.value) {
      time.value = stationMeta.default_origin || time.value
      await load()
    }
  } catch (reason) {
    error.value = reason.message
  }
}

// 四个请求互不依赖，一个失败不影响其他三个显示
async function load() {
  if (!meta.value?.ready) {
    return
  }
  const token = ++request
  busy.value = true
  error.value = ''
  forecastError.value = ''
  const results = await Promise.allSettled([
    api('stations/snapshot', { time: time.value, city: city.value }),
    api('stations/history', { station_id: stationId.value, end: time.value, hours: 72 }),
    api('stations/trend', { station_id: stationId.value, year: year.value }),
    api('stations/forecast', { station_id: stationId.value, time: time.value, model: model.value }),
  ])
  if (token !== request) {
    return
  }
  const targets = [snapshot, history, trend, forecast]
  results.forEach((outcome, index) => {
    if (outcome.status === 'fulfilled') {
      targets[index].value = outcome.value
      return
    }
    targets[index].value = null
    if (index === 3) {
      forecastError.value = outcome.reason.message
    } else {
      error.value = outcome.reason.message
    }
  })
  busy.value = false
}

async function loadTrend() {
  try {
    trend.value = await api('stations/trend', { station_id: stationId.value, year: year.value })
  } catch (reason) {
    error.value = reason.message
  }
}

onMounted(async () => {
  await setup()
  // 流水线未完成时每 15 秒检查一次进度
  setupTimer = setInterval(() => {
    if (!meta.value?.ready) {
      setup()
    }
  }, 15000)
})

onBeforeUnmount(() => clearInterval(setupTimer))

watch(city, () => {
  const exists = stations.value.some(item => item.station_id === stationId.value)
  if (exists) {
    load()
  } else {
    stationId.value = stations.value[0]?.station_id || '1001A'
  }
})

watch(stationId, load)
watch(year, loadTrend)

function onMapSelect(event) {
  if (event.data?.id) {
    stationId.value = event.data.id
  }
}

// 把当前回放结果导出为 CSV（带 BOM，Excel 可直接打开中文）
function downloadCsv() {
  const result = forecast.value
  if (!result) {
    return
  }
  const header = ['站点', '预测起点', '目标时刻', '提前小时', 'Spark随机森林', 'CUDA TCN', '真实值', '持续性基线']
  const rows = result.points.map(point => [
    stationId.value,
    point.origin,
    point.target,
    point.horizon,
    point.rf,
    point.tcn72,
    point.actual ?? '',
    point.baseline,
  ])
  const text = '﻿' + [header, ...rows].map(row => row.join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `station_${stationId.value}_forecast.csv`
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
  const base = baseOption()
  return {
    ...base,
    legend: legend(['历史观测', 'CUDA TCN', 'Spark 随机森林', '后续真实值', '持续性基线']),
    grid: { ...base.grid, bottom: 62 },
    tooltip: { ...base.tooltip, formatter: timeTooltip() },
    xAxis: timeAxis(),
    yAxis: valueAxis(),
    dataZoom: zoomControls(55),
    series: [
      lineSeries({
        name: '历史观测',
        data: result.history.map(point => [axisTime(point.ts), point.pm25]),
        color: roleColors.observed,
      }),
      series('tcn72', 'CUDA TCN', modelColors.tcn72, { width: 2.5, z: 4 }),
      series('rf', 'Spark 随机森林', modelColors.rf, { z: 3 }),
      series('actual', '后续真实值', roleColors.observed, { dashed: true, z: 5 }),
      series('baseline', '持续性基线', roleColors.baseline, { dashed: true, points: false }),
    ],
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
      <div class="stat-row">
        <StatCard
          label="六城历史监测站点"
          :value="fmtInt(meta.summary.stations)"
          unit="个"
          :icon="Database"
          featured
          hint="包含期间停运和新增的站点"
        />
        <StatCard
          label="有效站点小时 PM₂.₅"
          :value="fmt(meta.summary.valid_pm25 / 10000, 1)"
          unit="万条"
          :hint="`完整小时网格 ${fmtInt(meta.summary.grid_hours)} 行`"
        />
        <StatCard
          label="全国原始档案"
          :value="fmtBytes(meta.summary.raw_archive_bytes)"
          :hint="`${fmtInt(meta.summary.source_file_count)} 份逐站小时文件`"
        />
        <StatCard
          label="CUDA 训练峰值利用率"
          :value="fmt(gpu?.peak_gpu_util_percent, 0)"
          unit="%"
          :icon="Cpu"
          :hint="gpu?.device"
        />
      </div>

      <PanelCard kicker="选择站点与时刻" title="历史回放：同一时刻的站点观测与两种模型预测">
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
            <select v-model="stationId">
              <option v-for="item in stations" :key="item.station_id" :value="item.station_id">
                {{ item.name }}（{{ item.station_id }}）
              </option>
            </select>
          </label>
          <label class="field">
            预测起点（北京时间）
            <input
              v-model="time"
              type="datetime-local"
              :min="meta.forecast_range?.[0]"
              :max="meta.forecast_range?.[1]"
              step="3600"
            />
          </label>
          <label class="field">
            选用模型
            <select v-model="model">
              <option v-for="(name, id) in stationModelNames" :key="id" :value="id">
                {{ name }}
              </option>
            </select>
          </label>
          <button class="button primary" type="button" :disabled="busy" @click="load">
            <ScanLine :size="15" />{{ busy ? '正在读取' : '读取观测与预测' }}
          </button>
        </div>
        <template #note>
          可选范围是 2024 年验证期和 2025 年测试期；训练期 2022—2023 年的样本不用于回放。
        </template>
      </PanelCard>

      <Notice v-if="busy" kind="loading">正在读取站点观测和真实模型输出…</Notice>

      <template v-else>
        <div class="grid-wide-left">
          <PanelCard
            kicker="站点观测 · 点击站点切换"
            :title="`${snapshot ? bjFull(snapshot.time) : ''} 各站点浓度`"
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
                    class="clickable"
                    :class="{ selected: item.station_id === stationId }"
                    @click="stationId = item.station_id"
                  >
                    <td>{{ item.name }} <span class="muted">{{ item.station_id }}</span></td>
                    <td class="num strong">{{ fmt(item.pm25) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </PanelCard>
        </div>

        <Notice v-if="forecastError" kind="error">{{ forecastError }}</Notice>

        <PanelCard
          v-if="forecast"
          kicker="CPU 与 GPU 模型的历史回放"
          :title="`${selected?.name || stationId}：未来六小时的两种预测`"
        >
          <template #actions>
            <span class="tag">起点 {{ fmt(forecast.current) }} μg/m³</span>
            <button class="button small" type="button" @click="downloadCsv">
              <Download :size="14" />导出 CSV
            </button>
          </template>
          <Chart :option="forecastOption" height="330px" label="站点 CPU 与 GPU 模型六小时预测与真实值" />
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>目标时刻</th>
                  <th class="num">Spark 随机森林</th>
                  <th class="num">CUDA TCN</th>
                  <th class="num">真实值</th>
                  <th class="num">持续性基线</th>
                  <th>本次选用</th>
                  <th class="num">选用结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="point in forecast.points" :key="point.horizon">
                  <td>
                    {{ bjFull(point.target) }} <span class="tag">+{{ point.horizon }} h</span>
                  </td>
                  <td class="num">{{ fmt(point.rf) }}</td>
                  <td class="num">{{ fmt(point.tcn72) }}</td>
                  <td class="num">{{ fmt(point.actual) }}</td>
                  <td class="num">{{ fmt(point.baseline) }}</td>
                  <td>{{ stationModelNames[point.model] }}</td>
                  <td class="num strong">{{ fmt(point.prediction) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <template #note>
            {{ forecast.split === 'test' ? '2025 年独立测试期：未参与模型选择。' : '2024 年验证期：用于选择推荐模型。' }}
            页面读取真实模型的批量输出；缺失的真实值不参与误差计算。
          </template>
        </PanelCard>

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
            :title="`${selected?.name || stationId}的日均浓度`"
            note="按有效小时计算日均值；全天无观测时保留空缺。"
          >
            <template #actions>
              <select v-model="year" class="select" aria-label="选择年份">
                <option v-for="item in yearOptions" :key="item" :value="item">{{ item }} 年</option>
              </select>
            </template>
            <Chart :option="trendOption" height="250px" label="所选站点日均 PM2.5" />
          </PanelCard>
        </div>
      </template>

      <PanelCard kicker="同一批样本上的比较" title="TCN、随机森林与持续性基线">
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

      <PanelCard v-if="gpu" kicker="CUDA 训练证据" title="显卡确实参与了训练">
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

      <div class="method-note">
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
