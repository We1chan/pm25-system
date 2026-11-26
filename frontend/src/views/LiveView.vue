<script setup>
/*
 * 实时预测页（第三代）。
 * 数据：/api/live/meta 每 5 秒轮询一次，拿到刷新进度、站点状态和本轮发布信息；
 *       轮次变化或切换站点时再读 /api/live/forecast；点击按钮调用 POST /api/live/refresh。
 * 规则：只展示"目标时刻都还在未来"的预测；过期或正在准备时明确提示，不展示旧结果冒充当前。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowRight,
  ArrowUpRight,
  Download,
  Info,
  LocateFixed,
  RefreshCw,
  Search,
} from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import PmLegend from '../components/PmLegend.vue'
import { api, apiHref, postApi } from '../lib/api'
import { bjDateTime, bjTime, fmt, fmtInt, fmtPercent, isNumber } from '../lib/format'
import { refreshPhaseText, refreshSteps, weatherVariables } from '../lib/labels'
import { verificationHref, verificationRecordsHref } from '../lib/liveLinks'
import {
  BAND_NAME,
  axisTime,
  bandSeries,
  barSeries,
  baseOption,
  legend,
  lineSeries,
  palette,
  pmColor,
  pointMapOption,
  referenceLine,
  roleColors,
  timeAxis,
  timeTooltip,
  valueAxis,
  zoomControls,
} from '../lib/chart'

const live = ref(null)
const forecast = ref(null)
const stationPreferenceKey = 'pm25-live-station'
const initialSelection = new URLSearchParams(location.hash.split('?')[1])
const selected = ref('')
const nearby = ref([])
const locating = ref(false)
const locationMessage = ref('')
const comparison = ref('')
const comparisonForecast = ref(null)
const comparisonError = ref('')
const stationQuery = ref('')
// 三类错误分开保存，各自在下一次成功时清除，避免一次网络抖动的提示一直留在页面上
const pollError = ref('')
const forecastError = ref('')
const refreshError = ref('')
const notice = ref('')
const requesting = ref(false)
const clock = ref(Date.now())
const weatherVar = ref('wind_speed_10m')
const reference = ref(75)

let pollTimer = 0
let clockTimer = 0
let forecastToken = 0
let lastCycle = ''
let cycleBeforeRefresh = ''
let polling = false
let active = true
let locationRequest = 0
let selectionRestored = false

// ---------- 状态推导 ----------

// 预测可用：后端标记可用，且六个目标时刻都还没到（已经过去的目标不能叫"预测"）
function usableForecast(result, stationId) {
  return live.value?.usable && result?.station_id === stationId && canForecast(stationId)
    && result.cycle_id === live.value.cycle_id
    && result.points?.length > 0
    && result.points.every(point => new Date(point.target).getTime() > clock.value)
}

const fresh = computed(() => usableForecast(forecast.value, selected.value))
const comparisonFresh = computed(() => Boolean(comparison.value)
  && usableForecast(comparisonForecast.value, comparison.value)
  && comparisonForecast.value.issued_at === forecast.value?.issued_at)

const refreshing = computed(() => requesting.value || Boolean(live.value?.refreshing))

// 当前处于刷新流水线的第几步；刚触发但进度文件还没更新时算第 0 步
const stepIndex = computed(() => {
  const phase = live.value?.refresh?.phase
  if (!refreshing.value) {
    return refreshSteps.length
  }
  if (phase === 'complete' || phase === 'initializing' || !phase) {
    return 0
  }
  return Math.max(0, refreshSteps.findIndex(step => step.id === phase))
})

const phaseText = computed(() => {
  const phase = live.value?.refresh?.phase
  if (live.value?.refreshing && phase === 'complete') {
    return '正在启动数据采集'
  }
  return refreshPhaseText[phase] || '正在更新'
})

const headline = computed(() => {
  if (!live.value?.ready) {
    return '正在准备实时输入'
  }
  if (live.value.usable) {
    return '最新实测已接入，当前预测有效'
  }
  return '当前没有有效预测'
})

const stations = computed(() => live.value?.stations || [])
const selectedStation = computed(() => stations.value.find(station => station.station_id === selected.value))
const selectedName = computed(() => selected.value === 'mean'
  ? '北京覆盖站点均值'
  : selectedStation.value?.name || selected.value)
const selectedDistance = computed(() => nearby.value.find(item => item.id === selected.value)?.km)
const nearestAvailable = computed(() => nearby.value.find(item => canForecast(item.id)))

const lastPoint = computed(() => forecast.value?.points.at(-1) || null)

function stationOptionText(station) {
  const suffix = station.available ? '' : ' · 暂不可预测'
  return `${station.name || '未命名站点'}（${station.station_id}）${suffix}`
}

// 用户自设的关注参考线：只做提示，不是官方预警
const riskText = computed(() => {
  const limit = Number(reference.value)
  if (!forecast.value || !Number.isFinite(limit)) {
    return ''
  }
  const points = forecast.value.points
  const median = points.filter(point => isNumber(point.prediction) && point.prediction >= limit)
  const upper = points.filter(point => isNumber(point.upper) && point.upper >= limit)
  if (median.length) {
    return `有 ${median.length} 个整点的预测中位数达到 ${limit} μg/m³。`
  }
  if (upper.length) {
    return `有 ${upper.length} 个整点的区间上沿超过 ${limit} μg/m³，需留意后续更新。`
  }
  if (points.some(point => !isNumber(point.upper))) {
    return `已有的预测值低于 ${limit} μg/m³，部分整点缺少预测区间。`
  }
  return `本轮预测和区间上沿都低于 ${limit} μg/m³。`
})

const stationRows = computed(() => [...stations.value].sort((a, b) => (b.current ?? -1) - (a.current ?? -1)))
const searchResults = computed(() => {
  const query = stationQuery.value.trim().toLowerCase()
  return stationRows.value.filter(station =>
    `${station.name || ''} ${station.station_id}`.toLowerCase().includes(query),
  )
})

const liveReturnHref = computed(() => {
  const query = new URLSearchParams({ station_id: selected.value })
  if (comparison.value) query.set('compare', comparison.value)
  return '#live?' + query.toString()
})
const exportHref = computed(() => apiHref('live/export', {
  station_id: forecast.value?.station_id, cycle_id: forecast.value?.cycle_id,
}))
const comparisonExportHref = computed(() => apiHref('live/export', {
  station_id: comparisonForecast.value?.station_id, cycle_id: comparisonForecast.value?.cycle_id,
}))
const forecastHours = computed(() => (forecast.value?.points || []).map((point, index, points) => {
  const previous = index === 0 ? forecast.value.current : points[index - 1].prediction
  const change = isNumber(point.prediction) && isNumber(previous)
    ? Math.round((Number(point.prediction) - Number(previous)) * 10) / 10
    : null
  return {
    ...point,
    range: intervalText(point),
    direction: change === null ? '趋势暂无' : change > 0 ? '↑ 上升' : change < 0 ? '↓ 下降' : '→ 持平',
    change,
  }
}))

function intervalText(point) {
  return isNumber(point.lower) && isNumber(point.upper)
    ? `${fmt(point.lower)}–${fmt(point.upper)}` : '区间暂无'
}

function canForecast(stationId) {
  return stationId === 'mean' || stations.value.some(station => station.station_id === stationId && station.available)
}

function findNearbyStations(latitude, longitude) {
  const radians = Math.PI / 180
  const userLatitude = latitude * radians
  return stations.value
    .filter(station => isNumber(station.latitude) && isNumber(station.longitude))
    .map(station => {
      const stationLatitude = station.latitude * radians
      const deltaLatitude = stationLatitude - userLatitude
      const deltaLongitude = (station.longitude - longitude) * radians
      const arc = Math.sin(deltaLatitude / 2) ** 2
        + Math.cos(userLatitude) * Math.cos(stationLatitude) * Math.sin(deltaLongitude / 2) ** 2
      return { id: station.station_id, km: 12742 * Math.asin(Math.sqrt(Math.min(1, arc))) }
    })
    .sort((a, b) => a.km - b.km)
}

function locateStation() {
  if (!navigator.geolocation) {
    locationMessage.value = '当前浏览器无法定位，请手动选择监测站。'
    return
  }
  const request = ++locationRequest
  locating.value = true
  locationMessage.value = ''
  navigator.geolocation.getCurrentPosition(({ coords }) => {
    if (!active || request !== locationRequest) return
    nearby.value = findNearbyStations(coords.latitude, coords.longitude)
    if (nearby.value.length) {
      selectStation(nearby.value[0].id)
    } else {
      locating.value = false
      locationMessage.value = '站点暂无坐标，请手动选择监测站。'
    }
  }, error => {
    if (!active || request !== locationRequest) return
    locating.value = false
    locationMessage.value = error.code === 1
      ? '浏览器未授权定位，请手动选站，或允许定位后重试。'
      : '暂时无法取得位置，请重试或手动选站。'
  }, { timeout: 8000 })
}

// ---------- 数据加载 ----------

async function loadForecast(stationId, target, error, token) {
  error.value = ''
  if (!stationId || !live.value?.usable || !canForecast(stationId)) {
    target.value = null
    return
  }
  try {
    const result = await api('live/forecast', { station_id: stationId, cycle_id: live.value.cycle_id })
    if (token === forecastToken) {
      target.value = result
    }
  } catch (reason) {
    if (token === forecastToken) {
      error.value = reason.message
    }
  }
}

function loadForecasts() {
  const token = ++forecastToken
  return Promise.all([
    loadForecast(selected.value, forecast, forecastError, token),
    loadForecast(comparison.value, comparisonForecast, comparisonError, token),
  ])
}

function restoreSelection() {
  if (selectionRestored || !stations.value.length || selected.value) return false
  selectionRestored = true
  const linkedStation = initialSelection.get('station_id')
  if (linkedStation === 'mean' || stations.value.some(station => station.station_id === linkedStation)) {
    selectStation(linkedStation)
    const linkedComparison = initialSelection.get('compare')
    if (linkedComparison !== linkedStation && stations.value.some(station => station.station_id === linkedComparison)) {
      comparison.value = linkedComparison
    }
  } else {
    try {
      const saved = localStorage.getItem(stationPreferenceKey)
      if (stations.value.some(station => station.station_id === saved)) selectStation(saved)
    } catch {
      // 浏览器不提供存储时，可以直接选站。
    }
  }
  return Boolean(selected.value)
}

async function poll() {
  if (polling) return
  polling = true
  try {
    const meta = await api('live/meta')
    if (!active) return
    live.value = meta
    pollError.value = ''
    const restored = restoreSelection()
    if (cycleBeforeRefresh && meta.cycle_id !== cycleBeforeRefresh && !meta.refreshing
      && meta.refresh?.phase === 'complete') {
      notice.value = '最新实测与预测已更新'
      cycleBeforeRefresh = ''
    }
    if (meta.refresh?.phase === 'failed' && !meta.refreshing) {
      notice.value = ''
      cycleBeforeRefresh = ''
    }
    const primaryNeedsData = canForecast(selected.value)
      && (forecast.value?.station_id !== selected.value || forecast.value?.issued_at !== meta.issued_at)
    const comparisonNeedsData = comparison.value && canForecast(comparison.value)
      && (comparisonForecast.value?.station_id !== comparison.value || comparisonForecast.value?.issued_at !== meta.issued_at)
    if (meta.cycle_id !== lastCycle || (meta.usable && (primaryNeedsData || comparisonNeedsData))) {
      lastCycle = meta.cycle_id
      if (!restored) await loadForecasts()
    }
  } catch (reason) {
    pollError.value = reason.message
  } finally {
    polling = false
  }
}

async function refresh() {
  requesting.value = true
  notice.value = ''
  refreshError.value = ''
  try {
    const result = await postApi('live/refresh')
    notice.value = result.message
    if (result.accepted) cycleBeforeRefresh = live.value?.cycle_id || ''
    await poll()
  } catch (reason) {
    refreshError.value = reason.message
  } finally {
    requesting.value = false
  }
}

function selectStation(stationId) {
  locationRequest += 1
  locating.value = false
  locationMessage.value = ''
  if (stationId === comparison.value) comparison.value = ''
  selected.value = stationId
  if (stationId && stationId !== 'mean') {
    try {
      localStorage.setItem(stationPreferenceKey, stationId)
    } catch {
      // 私密浏览或禁用存储时仍可在当前页面选站。
    }
  }
}

function onMapSelect(event) {
  if (event.data?.id) {
    selectStation(event.data.id)
  }
}

watch([selected, comparison], loadForecasts)

onMounted(async () => {
  await poll()
  if (!active) return
  pollTimer = setInterval(poll, 5000)
  clockTimer = setInterval(() => {
    clock.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  active = false
  forecastToken += 1
  clearInterval(pollTimer)
  clearInterval(clockTimer)
})

// ---------- 图表 ----------

const sharedYAxisMax = computed(() => {
  if (!fresh.value || !comparisonFresh.value) return undefined
  const values = [forecast.value, comparisonForecast.value].flatMap(result => [
    result.current,
    ...result.history.map(point => point.pm25),
    ...result.points.flatMap(point => [point.prediction, point.upper, point.baseline]),
  ])
  const limit = isNumber(reference.value) ? Number(reference.value) : 0
  const peak = Math.max(10, limit, ...values.filter(isNumber).map(Number))
  return Math.ceil(peak / 10) * 10
})

function makeForecastOption(result) {
  if (!result) {
    return null
  }
  const origin = axisTime(result.origin)
  const start = [origin, result.current]
  const history = result.history.map(point => [axisTime(point.ts), point.pm25])
  const predictions = [
    { value: start },
    ...result.points.map(point => ({
      value: [axisTime(point.target), point.prediction],
      lower: point.lower,
      upper: point.upper,
      // 递推延伸的点用橙色标出，表示误差可能更大
      itemStyle: point.method === 'recursive_extension' ? { color: palette.orange } : undefined,
    })),
  ]
  const baseline = [start, ...result.points.map(point => [axisTime(point.target), point.baseline])]
  const names = ['历史实测', '当前预测', '持续性基线']
  let band = []
  if (result.points.length && result.points.every(point => isNumber(point.lower) && isNumber(point.upper))) {
    const lower = [start, ...result.points.map(point => [axisTime(point.target), point.lower])]
    const upper = [start, ...result.points.map(point => [axisTime(point.target), point.upper])]
    band = bandSeries(lower, upper)
    names.push(BAND_NAME)
  }
  const base = baseOption()
  const limit = Number(reference.value)
  return {
    ...base,
    legend: legend(names),
    grid: { ...base.grid, bottom: 62 },
    tooltip: { ...base.tooltip, formatter: timeTooltip() },
    xAxis: timeAxis(),
    yAxis: valueAxis('μg/m³', { max: sharedYAxisMax.value }),
    dataZoom: zoomControls(50),
    series: [
      ...band,
      lineSeries({ name: '历史实测', data: history, color: roleColors.observed, z: 3 }),
      lineSeries({
        name: '当前预测',
        data: predictions,
        color: palette.green,
        width: 2.5,
        points: true,
        z: 4,
        markLine: Number.isFinite(limit) && limit > 0 ? referenceLine(limit, '关注参考线') : undefined,
      }),
      lineSeries({ name: '持续性基线', data: baseline, color: roleColors.baseline, dashed: true }),
    ],
  }
}

const forecastOption = computed(() => fresh.value ? makeForecastOption(forecast.value) : null)
const comparisonOption = computed(() => comparisonFresh.value ? makeForecastOption(comparisonForecast.value) : null)

const weatherOption = computed(() => {
  const result = forecast.value
  if (!result) {
    return null
  }
  const key = weatherVar.value
  const variable = weatherVariables[key]
  const past = result.history.map(point => [axisTime(point.ts), point[key]])
  const next = (result.weather_next || []).map(point => [axisTime(point.ts), point[key]])
  const base = baseOption()
  const isRain = key === 'precipitation'
  // 过去与未来是同一个量的不同来源：同色，未来用虚线（降水用浅色柱）
  const makeSeries = (name, data, isFuture) => {
    if (isRain) {
      const color = isFuture ? '#9ec5f4' : palette.blue
      return barSeries({ name, data, color, width: 6 })
    }
    return lineSeries({ name, data, color: palette.blue, dashed: isFuture })
  }
  return {
    ...base,
    legend: legend(['过去 72 小时（模型输入）', '未来预报']),
    tooltip: { ...base.tooltip, formatter: timeTooltip({ unit: variable.unit }) },
    xAxis: timeAxis(),
    yAxis: valueAxis(variable.unit, { scale: !isRain }),
    series: [
      makeSeries('过去 72 小时（模型输入）', past, false),
      makeSeries('未来预报', next, true),
    ],
  }
})

const mapOption = computed(() => {
  const points = (live.value?.stations || [])
    .filter(station => isNumber(station.latitude) && isNumber(station.longitude))
    .map(station => ({
      id: station.station_id,
      name: `${station.name}（${station.station_id}）`,
      lon: station.longitude,
      lat: station.latitude,
      value: station.current,
      color: station.available ? undefined : '#89938e',
    }))
  return pointMapOption({
    points,
    selectedId: selected.value,
    center: [116.38, 40.15],
    zoom: 3.6,
    highlight: ['北京市'],
  })
})
</script>

<template>
  <div class="stack">
    <Notice v-if="pollError" kind="error">{{ pollError }}</Notice>
    <Notice v-if="refreshError" kind="error">
      {{ refreshError }}。
      <span v-if="live?.issued_at">上次成功发布于 {{ bjDateTime(live.issued_at) }}。</span>
    </Notice>
    <Notice v-if="!live && !pollError" kind="loading">正在连接实时预测服务…</Notice>

    <template v-if="live">
      <!-- 状态条：当前是否有有效预测、刷新进度和手动刷新按钮 -->
      <section class="panel status-bar">
        <div class="status-main">
          <div class="status-title">
            <span class="dot" :class="{ live: live.usable, off: !live.usable }"></span>
            <strong>{{ headline }}</strong>
          </div>
          <div class="status-times">
            <span>实测起点 <b>{{ bjDateTime(fresh ? forecast.origin : live.origin) }}</b></span>
            <ArrowRight :size="13" aria-hidden="true" />
            <span>预测发布 <b>{{ bjDateTime(fresh ? forecast.issued_at : live.issued_at) }}</b></span>
            <template v-if="live.next_refresh">
              <ArrowRight :size="13" aria-hidden="true" />
              <span>下次自动更新约 <b>{{ bjTime(live.next_refresh) }}</b></span>
            </template>
          </div>
        </div>

        <ol v-if="refreshing" class="steps" aria-label="实时更新进度">
          <li
            v-for="(step, index) in refreshSteps"
            :key="step.id"
            :class="{ done: index < stepIndex, current: index === stepIndex }"
            :aria-current="index === stepIndex ? 'step' : undefined"
          >
            <span class="step-mark">{{ index < stepIndex ? '✓' : index + 1 }}</span>
            {{ step.name }}
          </li>
        </ol>
        <button class="button small" type="button" :disabled="refreshing" @click="refresh">
          <RefreshCw :size="15" :class="{ spinning: refreshing }" aria-hidden="true" />
          {{ refreshing ? '正在更新数据' : '手动更新数据' }}
        </button>
      </section>

      <Notice v-if="notice" kind="good">{{ notice }}</Notice>
      <Notice v-if="live.refreshing" kind="loading">
        {{ phaseText }}。{{ fresh ? '当前仍显示上一轮有效预测。' : '' }}
      </Notice>
      <Notice v-if="live.refresh?.phase === 'failed'" kind="error">
        {{ live.refresh.error }}。
        <span v-if="live.issued_at">上次成功发布于 {{ bjDateTime(live.issued_at) }}。</span>
        {{ fresh ? '上一轮预测仍有效。' : '正在等待可用预测。' }}
      </Notice>
      <Notice v-if="live.source_errors?.length" kind="warn">
        本轮有部分原始资料未能获取，预测只使用已成功取得的资料；请结合实测时刻和可预测站点数判断。
      </Notice>

      <PanelCard v-if="!live.ready" title="正在建立最近 72 小时的实时输入">
        <p class="panel-text">
          {{ phaseText }}。首次运行需要补齐最近几天的站点记录，然后由 Spark 构建小时网格，再运行已训练模型。
        </p>
      </PanelCard>

      <template v-else>
        <PanelCard
          :title="selected ? `${selectedName} · 未来六个整点` : '查看附近站点预测'"
          class="forecast-summary"
        >
          <template #actions>
            <a v-if="fresh && forecast.cycle_id" class="button small"
              :href="selected === 'mean' ? verificationRecordsHref(forecast, liveReturnHref) : verificationHref(forecast.cycle_id, selected, undefined, liveReturnHref)">
              {{ selected === 'mean' ? '查看本轮逐站核验' : '查看本站本轮核验' }}
            </a>
          </template>
          <div class="forecast-location">
            <button class="button" :class="{ primary: !selected }" type="button"
              :disabled="locating || !stations.length" @click="locateStation">
              <LocateFixed :size="16" aria-hidden="true" />
              {{ locating ? '正在定位…' : '定位最近站点' }}
            </button>
            <label class="location-station">
              监测站
              <select class="select" :value="selected" @change="selectStation($event.target.value)">
                <option value="" disabled>选择监测站</option>
                <option value="mean">北京覆盖站点均值（参考）</option>
                <option v-for="station in stations" :key="station.station_id" :value="station.station_id">
                  {{ stationOptionText(station) }}
                </option>
              </select>
            </label>
            <span v-if="selectedDistance != null" class="panel-text">
              {{ selected === nearby[0]?.id ? '最近站 · ' : '' }}直线距离约 {{ fmt(selectedDistance) }} 公里
            </span>
          </div>
          <p v-if="locationMessage" class="panel-text location-message" role="status">{{ locationMessage }}</p>
          <p v-if="selected === 'mean'" class="panel-text location-message">
            本轮覆盖 {{ fmtInt(live.forecast_stations) }} / {{ fmtInt(live.beijing_stations) }} 个北京站点。
          </p>
          <template v-if="fresh">
            <p class="strip-context">
              {{ bjTime(forecast.origin) }} 实测 {{ fmt(forecast.current) }} μg/m³
              <span v-if="isNumber(live.nominal_coverage)"> · 预计范围为 {{ fmtPercent(live.nominal_coverage, 0) }} 预测区间</span>
              <span> · 序号从发布后的第一个整点算起</span>
            </p>
            <ol class="strip" aria-label="未来六个整点 PM₂.₅ 预测">
              <li v-for="point in forecastHours" :key="point.target">
                <i class="strip-level" :style="{ background: pmColor(point.prediction) }"></i>
                <span class="strip-time">{{ bjTime(point.target) }} · 第 {{ point.horizon }} 个整点</span>
                <span class="strip-value"><strong>{{ fmt(point.prediction) }}</strong> <small>μg/m³</small></span>
                <span class="strip-sub">{{ point.range }}</span>
                <span class="strip-trend" :class="{ rising: point.change > 0, falling: point.change < 0 }">
                  {{ point.direction }}
                </span>
                <span v-if="point.method === 'recursive_extension'" class="tag warn">递推延伸</span>
              </li>
            </ol>
          </template>
          <Notice v-else-if="selectedStation && !selectedStation.available" kind="warn">
            {{ selectedName }}本轮暂不可预测。{{ selectedStation.reason || '缺少所需输入资料' }}
            <button v-if="nearestAvailable && live.usable" class="button small" type="button"
              @click="selectStation(nearestAvailable.id)">
              查看附近可预测站点
            </button>
          </Notice>
          <p v-else-if="!selected" class="panel-text location-message">定位后会选中距离最近的监测站。也可以按站名手动选择。</p>
          <Notice v-else-if="forecastError" kind="error">{{ forecastError }}</Notice>
          <Notice v-else-if="live.usable && forecast?.station_id !== selected" kind="loading">正在读取站点预测…</Notice>
          <Notice v-else kind="warn">上一轮预测已过期，正在等待新的当前预测。</Notice>
        </PanelCard>

        <div class="station-workspace">
          <PanelCard :title="selected ? `${selectedName} · 实测与预测` : '站点实测与预测'">
            <template #actions>
              <a v-if="fresh" class="button small" :href="exportHref"><Download :size="14" />导出 CSV</a>
            </template>
            <label v-if="fresh && stations.length" class="comparison-picker">
              对比站点
              <select v-model="comparison" class="select" aria-label="选择对比站点">
                <option value="">不比较</option>
                <option v-for="station in stations" :key="station.station_id"
                  :value="station.station_id" :disabled="!station.available || station.station_id === selected">
                  {{ stationOptionText(station) }}
                </option>
              </select>
            </label>
            <div class="comparison-grid" :class="{ comparing: comparison }">
              <div>
                <h3 v-if="comparison">{{ selectedName }}</h3>
                <Chart v-if="fresh" :option="forecastOption" height="320px" :label="`${selectedName}实测和预测曲线`" />
                <Notice v-else-if="selectedStation && !selectedStation.available" kind="warn">
                  {{ selectedStation.reason || '该站点本轮缺少所需输入资料。' }}
                </Notice>
                <Notice v-else-if="forecastError" kind="error">{{ forecastError }}</Notice>
                <p v-else class="panel-text">{{ selected ? '等待可用预测。' : '选择监测站后查看曲线。' }}</p>
              </div>
              <div v-if="comparison">
                <h3>{{ stations.find(station => station.station_id === comparison)?.name || comparison }}</h3>
                <template v-if="comparisonFresh">
                  <Chart :option="comparisonOption" height="320px" :label="`${comparisonForecast.name}对比曲线`" />
                  <a class="button small" :href="comparisonExportHref"><Download :size="14" />导出对比站 CSV</a>
                  <a class="button small" :href="verificationHref(comparisonForecast.cycle_id, comparison, undefined, liveReturnHref)">
                    查看对比站核验
                  </a>
                </template>
                <Notice v-else-if="comparisonError" kind="error">{{ comparisonError }}</Notice>
                <p v-else-if="!canForecast(comparison)" class="panel-text">对比站点本轮暂不可预测。</p>
                <p v-else class="panel-text">等待与主站点同轮的预测。</p>
              </div>
            </div>
          </PanelCard>

          <PanelCard title="北京站点地图">
            <template #actions>
              <label class="station-search">
                <Search :size="16" aria-hidden="true" />
                <input v-model="stationQuery" type="search" placeholder="站名或编号" aria-label="搜索站点" />
              </label>
            </template>
            <Chart
              :option="mapOption"
              height="300px"
              label="北京各站点最新 PM2.5 地图"
              @select="onMapSelect"
            />
            <PmLegend />
            <template #note>点选站点会更新预测和曲线。灰色站点本轮不可预测，点开可查看原因。</template>
            <ul v-if="stationQuery.trim()" class="station-results" aria-label="站点搜索结果">
              <li v-for="station in searchResults" :key="station.station_id">
                <button type="button" class="button small" :aria-pressed="selected === station.station_id"
                  @click="selectStation(station.station_id)">
                  {{ stationOptionText(station) }}
                </button>
              </li>
              <li v-if="!searchResults.length" class="panel-text">没有匹配的站点。</li>
            </ul>
          </PanelCard>
        </div>

        <PanelCard v-if="fresh" title="预测明细">

          <div class="forecast-foot">
            <label class="reference">
              关注参考线
              <input
                v-model.number="reference"
                type="number"
                min="1"
                max="1000"
                aria-label="关注参考线"
              />
              μg/m³
            </label>
            <p>{{ riskText }} <span class="muted">（自设参考线，不是官方污染预警）</span></p>
          </div>

          <details class="more">
            <summary>查看逐小时明细</summary>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>目标时刻</th>
                    <th>发布后第几个整点</th>
                    <th class="num">预测 PM₂.₅</th>
                    <th class="num">预测区间</th>
                    <th class="num">持续性基线</th>
                    <th>距实测起点</th>
                    <th>生成方式</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="point in forecast.points" :key="point.target">
                    <td>{{ bjDateTime(point.target) }}</td>
                    <td>第 {{ point.horizon }} 个</td>
                    <td class="num strong">{{ fmt(point.prediction) }}</td>
                    <td class="num">
                      {{ intervalText(point) }}
                    </td>
                    <td class="num">{{ fmt(point.baseline) }}</td>
                    <td>+{{ point.lead_from_observation }} h</td>
                    <td>{{ point.method === 'recursive_extension' ? '递推延伸' : '模型直出' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </details>

          <template #note>
            六个目标时刻都在发布时间之后，真实浓度此时未知。
            {{ live.extension_hours
              ? `实测存在延迟，最后 ${live.extension_hours} 个整点通过递推覆盖，误差可能更大。`
              : '本轮六个整点均由模型直接输出。' }}
            {{ live.interval_note }}
            {{ bjDateTime(lastPoint?.target) }} 预计 {{ fmt(lastPoint?.prediction) }} μg/m³。
            历史测试显示，高浓度和浓度突变时区间覆盖不足。<a href="#online">查看在线核验 →</a>
          </template>
        </PanelCard>

        <details class="panel more station-details">
          <summary>查看全部站点状态（{{ stations.length }}）</summary>
            <div class="table-wrap tall">
              <table>
                <thead>
                  <tr>
                    <th>站点</th>
                    <th class="num">当前 PM₂.₅</th>
                    <th class="num">72h 有效小时</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="station in stationRows"
                    :key="station.station_id"
                    :class="{ selected: station.station_id === selected }"
                  >
                    <td>
                      <button type="button" class="station-link" :aria-pressed="station.station_id === selected"
                        @click="selectStation(station.station_id)">
                        {{ station.name }} <span class="muted">{{ station.station_id }}</span>
                      </button>
                    </td>
                    <td class="num strong">{{ fmt(station.current) }}</td>
                    <td class="num">{{ fmtInt(station.valid_history_hours) }}</td>
                    <td>
                      <span v-if="station.available" class="tag good">可预测</span>
                      <span v-else class="tag">{{ station.reason || '暂不可预测' }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
        </details>

        <details v-if="fresh" class="more weather-details">
          <summary>查看模型使用的天气资料</summary>
          <div class="grid-wide-left">
          <PanelCard kicker="天气输入" title="模型读取的天气：过去 72 小时 + 未来预报">
            <template #actions>
              <select v-model="weatherVar" class="select" aria-label="选择气象变量">
                <option v-for="(variable, key) in weatherVariables" :key="key" :value="key">
                  {{ variable.name }}
                </option>
              </select>
            </template>
            <Chart :option="weatherOption" height="280px" label="模型使用的过去与未来天气" />
            <template #note>
              城市代表点的天气模型格点资料，同城站点共享，不是空气站的气象实测。
              {{ live.future_weather
                ? '训练和线上都使用 GFS 提前 24 小时发布的预报，口径一致。'
                : '旧模型的历史实验使用 ERA5。' }}
            </template>
          </PanelCard>

          <PanelCard title="用于预测的城市天气资料">
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>时刻</th>
                    <th class="num">气温 °C</th>
                    <th class="num">湿度 %</th>
                    <th class="num">风速 m/s</th>
                    <th class="num">降水 mm</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="point in forecast.weather_next" :key="point.ts">
                    <td>{{ bjTime(point.ts) }}</td>
                    <td class="num">{{ fmt(point.temperature_2m) }}</td>
                    <td class="num">{{ fmt(point.relative_humidity_2m, 0) }}</td>
                    <td class="num">{{ fmt(point.wind_speed_10m) }}</td>
                    <td class="num">{{ fmt(point.precipitation) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <template #note>未来的污染物浓度在发布时未知，模型只读取未来的天气预报。</template>
          </PanelCard>
          </div>
        </details>

        <PanelCard title="当前模型的在线核验">
          <template #actions>
            <a href="#online" class="button small">查看核验进度与误差</a>
          </template>
          <p class="panel-text">
            当前模型累计已匹配 {{ fmtInt(live.online_evaluation?.matched) }} 条，等待实测
            {{ fmtInt(live.online_evaluation?.pending) }} 条。每条记录对应一个站点和一个目标整点。
          </p>
          <template #note>在线误差按单站预测计算。</template>
        </PanelCard>

        <details class="panel more technical-details">
          <summary>本轮数据来源与处理记录</summary>
          <dl class="run-details">
            <div><dt>发布轮次</dt><dd><code>{{ live.cycle_id || '—' }}</code></dd></div>
            <div><dt>模型 SHA-256</dt><dd><code>{{ live.checkpoint_sha256 || '—' }}</code></dd></div>
            <div><dt>HDFS 归档路径</dt><dd><code>{{ live.hdfs || '—' }}</code></dd></div>
          </dl>
          <ol class="pipeline">
            <li>
              <span class="pipe-step">1 · 采集</span>
              <strong>{{ (live.air_sources || []).map(source => source.name).join(' + ') || '—' }}</strong>
              <span>{{ live.weather_source?.name }}</span>
              <small>采集于 {{ bjDateTime(live.source_fetched_at) }}</small>
            </li>
            <li>
              <span class="pipe-step">2 · HDFS</span>
              <strong>原始文件与清单入库</strong>
            </li>
            <li>
              <span class="pipe-step">3 · Spark</span>
              <strong>Spark {{ live.spark_version }} 清洗与融合</strong>
              <span>补齐小时网格、合并天气，构建 {{ live.history_hours }} 小时窗口</span>
            </li>
            <li>
              <span class="pipe-step">4 · 模型推理</span>
              <strong>{{ live.model_name }}</strong>
              <span>{{ live.inference_device }}</span>
              <small>{{ live.engine }}</small>
            </li>
            <li>
              <span class="pipe-step">5 · 发布与核验</span>
              <strong>发布 {{ live.forecast_stations }} 个站点 + 均值</strong>
              <span>写入在线核验库，等待实测到达</span>
            </li>
          </ol>
          <p class="panel-note">
            页面会运行已训练模型推理，但更新数据不会重新训练模型。来源：
            <a
              v-for="source in live.air_sources"
              :key="source.url"
              :href="source.url"
              target="_blank"
              rel="noreferrer"
            >
              {{ source.name }}<ArrowUpRight :size="12" />
            </a>
            <a v-if="live.weather_source?.url" :href="live.weather_source.url" target="_blank" rel="noreferrer">
              天气接口说明<ArrowUpRight :size="12" />
            </a>
          </p>
        </details>

        <div class="method-note">
          <Info :size="16" aria-hidden="true" />
          <p>{{ live.method_note }} {{ live.accuracy_note }}</p>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.forecast-location,
.location-station {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  min-width: 0;
}

.forecast-location {
  margin-bottom: 12px;
}

.location-station {
  max-width: 100%;
  font-size: 13px;
}

.location-station select {
  min-width: 0;
  max-width: 100%;
}

.location-message {
  margin-block: 8px;
}

.weather-details > div {
  margin-top: 12px;
}

.status-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 16px 28px;
}

.status-main {
  flex: 1 1 320px;
}

.status-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
}

.status-times {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 13px;
  color: var(--ink-3);
}

.status-times b {
  color: var(--ink);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.steps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 13px;
  color: var(--ink-3);
}

.steps li {
  display: flex;
  align-items: center;
  gap: 6px;
}

.step-mark {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  font-size: 11px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
}

.steps li.done {
  color: var(--good);
}

.steps li.done .step-mark {
  border-color: var(--good);
  background: var(--good-soft);
}

.steps li.current {
  color: var(--brand-strong);
  font-weight: 600;
}

.steps li.current .step-mark {
  border-color: var(--brand);
  background: var(--brand);
  color: #fff;
  animation: pulse 1.6s ease-in-out infinite;
}

.strip-context {
  margin: 0 0 12px;
  color: var(--ink-2);
  font-size: 13px;
}

.strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.strip li {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 12px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-sunken);
  overflow: hidden;
}

.strip-level {
  position: absolute;
  inset: 0 0 auto 0;
  height: 4px;
}

.strip-time {
  font-size: 12px;
  color: var(--ink-3);
  white-space: nowrap;
}

.strip strong {
  font-size: clamp(22px, 2.3vw, 32px);
  font-weight: 650;
  line-height: 1.25;
}

.strip-sub {
  font-size: 12px;
  color: var(--ink-2);
  font-variant-numeric: tabular-nums;
}

.strip-value {
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.strip-value small {
  color: var(--ink-3);
}

.strip-trend {
  margin-top: 3px;
  color: var(--ink-2);
  font-size: 12px;
  font-weight: 600;
}

.strip-trend.rising { color: var(--warn); }
.strip-trend.falling { color: var(--good); }

.strip .tag {
  align-self: flex-start;
  margin-top: 4px;
}

.station-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(250px, 0.9fr);
  align-items: start;
  gap: 16px;
}

.station-workspace > * {
  min-width: 0;
}

.station-search,
.comparison-picker {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: var(--ink-2);
  font-size: 13px;
}

.station-search {
  flex-wrap: nowrap;
  padding: 0 9px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
}

.station-search input {
  width: 9rem;
  min-width: 0;
  min-height: 36px;
  border: 0;
  background: transparent;
  color: var(--ink);
}

.station-results {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 9rem;
  margin: 10px 0 0;
  padding: 2px;
  overflow: auto;
  list-style: none;
}

.comparison-picker select {
  max-width: 100%;
}

.comparison-grid {
  display: grid;
  gap: 16px;
  margin-top: 10px;
}

.comparison-grid.comparing {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.comparison-grid > div { min-width: 0; }
.comparison-grid h3 { margin: 6px 0; font-size: 14px; }

.station-link {
  padding: 3px 0;
  border: 0;
  background: transparent;
  color: var(--brand-strong);
  font: inherit;
  text-align: left;
  text-decoration: underline;
  cursor: pointer;
}

.station-details,
.technical-details {
  margin-top: 0;
}

.run-details {
  display: grid;
  gap: 8px;
  margin: 12px 0;
}

.run-details > div {
  display: grid;
  grid-template-columns: minmax(0, 8rem) minmax(0, 1fr);
  gap: 6px;
}

.run-details dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.forecast-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 18px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  font-size: 13px;
  color: var(--ink-2);
}

.reference {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.reference input {
  width: 76px;
  min-height: 30px;
  padding: 0 8px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
}

/* 本轮流水线：五个阶段从左到右 */
.pipeline {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: none;
}

.pipeline li {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  font-size: 12px;
  color: var(--ink-2);
  min-width: 0;
  overflow-wrap: anywhere;
}

.pipeline li:not(:last-child)::after {
  content: "→";
  position: absolute;
  top: 50%;
  right: -10px;
  transform: translateY(-50%);
  color: var(--ink-3);
  font-size: 13px;
}

.pipe-step {
  font-size: 12px;
  font-weight: 650;
  color: var(--brand);
}

.pipeline strong {
  font-size: 13px;
  color: var(--ink);
}

.pipeline small {
  color: var(--ink-3);
}

@media (max-width: 1180px) {
  .strip {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .pipeline {
    grid-template-columns: minmax(0, 1fr);
  }

  .pipeline li:not(:last-child)::after {
    content: "↓";
    top: auto;
    right: auto;
    bottom: -16px;
    left: 20px;
    transform: none;
  }
}

@media (max-width: 940px) {
  .station-workspace {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 600px) {
  .strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .comparison-grid.comparing,
  .run-details > div {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
