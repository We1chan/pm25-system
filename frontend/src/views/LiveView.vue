<script setup>
/*
 * 实时预测页（第三代）。
 * 数据：/api/live/meta 每 5 秒轮询一次，拿到刷新进度、站点状态和本轮发布信息；
 *       轮次变化或切换站点时再读 /api/live/forecast；点击按钮调用 POST /api/live/refresh。
 * 规则：只展示"目标时刻都还在未来"的预测；过期或正在准备时明确提示，不展示旧结果冒充当前。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Clock3,
  Download,
  Info,
  MapPin,
  RefreshCw,
  Thermometer,
} from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import PmLegend from '../components/PmLegend.vue'
import StatCard from '../components/StatCard.vue'
import { api, apiHref, postApi } from '../lib/api'
import { bjDateTime, bjTime, fmt, fmtInt, minutesSince } from '../lib/format'
import { refreshPhaseText, refreshSteps, weatherVariables } from '../lib/labels'
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
const selected = ref('mean')
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

// ---------- 状态推导 ----------

// 预测可用：后端标记可用，且六个目标时刻都还没到（已经过去的目标不能叫"预测"）
const fresh = computed(() => {
  if (!live.value?.usable || !forecast.value) {
    return false
  }
  return forecast.value.points.every(point => new Date(point.target).getTime() > clock.value)
})

const dataAge = computed(() => minutesSince(live.value?.origin, clock.value))

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
  if (fresh.value) {
    return '最新实测已接入，当前预测有效'
  }
  return '当前没有有效预测'
})

const selectedName = computed(() => forecast.value?.name || '北京覆盖站点均值')

const startWeather = computed(() => forecast.value?.history.at(-1) || null)

const lastPoint = computed(() => forecast.value?.points.at(-1) || null)

const hasInterval = computed(() => {
  const points = forecast.value?.points || []
  return points.length > 0 && points.every(point => point.lower !== null && point.upper !== null)
})

const weatherHint = computed(() => {
  const wind = fmt(startWeather.value?.wind_speed_10m)
  const humidity = fmt(startWeather.value?.relative_humidity_2m, 0)
  return `风速 ${wind} m/s · 湿度 ${humidity}%`
})

function stationOptionText(station) {
  const suffix = station.available ? '' : ' · 暂不可预测'
  return `${station.name}（${station.station_id}）${suffix}`
}

// 用户自设的关注参考线：只做提示，不是官方预警
const riskText = computed(() => {
  const limit = Number(reference.value)
  if (!forecast.value || !Number.isFinite(limit)) {
    return ''
  }
  const median = forecast.value.points.filter(point => point.prediction >= limit)
  const upper = forecast.value.points.filter(point => point.upper !== null && point.upper >= limit)
  if (median.length) {
    return `有 ${median.length} 个整点的预测中位数达到 ${limit} μg/m³。`
  }
  if (upper.length) {
    return `有 ${upper.length} 个整点的区间上沿超过 ${limit} μg/m³，需留意后续更新。`
  }
  return `本轮预测和区间上沿都低于 ${limit} μg/m³。`
})

const stationRows = computed(() => {
  const rows = [...(live.value?.stations || [])]
  return rows.sort((a, b) => (b.current ?? -1) - (a.current ?? -1))
})

const exportHref = computed(() => apiHref('live/export', { station_id: selected.value }))

// ---------- 数据加载 ----------

async function loadForecast() {
  const token = ++forecastToken
  if (!live.value?.usable) {
    // 不可用的原因已由状态条和提示说明，这里不再重复报错
    forecast.value = null
    forecastError.value = ''
    return
  }
  try {
    const result = await api('live/forecast', { station_id: selected.value })
    if (token === forecastToken) {
      forecast.value = result
      forecastError.value = ''
    }
  } catch (reason) {
    if (token === forecastToken) {
      forecast.value = null
      forecastError.value = reason.message
    }
  }
}

async function poll() {
  try {
    const meta = await api('live/meta')
    live.value = meta
    pollError.value = ''
    // 选中的站点本轮不可预测时退回均值，避免停留在一个没有结果的站点
    const stillAvailable = meta.stations.some(station => {
      return station.station_id === selected.value && station.available
    })
    if (selected.value !== 'mean' && !stillAvailable) {
      selected.value = 'mean'
    }
    if (cycleBeforeRefresh && meta.cycle_id !== cycleBeforeRefresh && !meta.refreshing) {
      notice.value = '最新实测与预测已更新'
      cycleBeforeRefresh = ''
    }
    if (meta.cycle_id !== lastCycle || !forecast.value) {
      lastCycle = meta.cycle_id
      await loadForecast()
    }
  } catch (reason) {
    pollError.value = reason.message
  }
}

async function refresh() {
  requesting.value = true
  notice.value = ''
  refreshError.value = ''
  try {
    const result = await postApi('live/refresh')
    notice.value = result.message
    cycleBeforeRefresh = live.value?.cycle_id || ''
    await poll()
  } catch (reason) {
    refreshError.value = reason.message
  } finally {
    requesting.value = false
  }
}

function selectStation(stationId) {
  const station = live.value?.stations.find(item => item.station_id === stationId)
  if (station?.available) {
    selected.value = stationId
  }
}

function onMapSelect(event) {
  if (event.data?.id) {
    selectStation(event.data.id)
  }
}

watch(selected, loadForecast)

onMounted(async () => {
  await poll()
  pollTimer = setInterval(poll, 5000)
  clockTimer = setInterval(() => {
    clock.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  clearInterval(pollTimer)
  clearInterval(clockTimer)
})

// ---------- 图表 ----------

const forecastOption = computed(() => {
  const result = forecast.value
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
  if (hasInterval.value) {
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
    yAxis: valueAxis(),
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
})

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
    .filter(station => station.latitude !== null && station.longitude !== null)
    .map(station => ({
      id: station.station_id,
      name: `${station.name}（${station.station_id}）`,
      lon: station.longitude,
      lat: station.latitude,
      value: station.current,
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
    <Notice v-if="refreshError" kind="error">{{ refreshError }}</Notice>
    <Notice v-if="forecastError" kind="error">{{ forecastError }}</Notice>
    <Notice v-if="!live && !pollError" kind="loading">正在连接实时预测服务…</Notice>

    <template v-if="live">
      <!-- 状态条：当前是否有有效预测、刷新进度和手动刷新按钮 -->
      <section class="panel status-bar">
        <div class="status-main">
          <div class="status-title">
            <span class="dot" :class="{ live: fresh, off: !fresh }"></span>
            <strong>{{ headline }}</strong>
          </div>
          <div class="status-times">
            <span>实测起点 <b>{{ bjDateTime(live.origin) }}</b></span>
            <ArrowRight :size="13" aria-hidden="true" />
            <span>预测发布 <b>{{ bjDateTime(live.issued_at) }}</b></span>
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
          >
            <span class="step-mark">{{ index < stepIndex ? '✓' : index + 1 }}</span>
            {{ step.name }}
          </li>
        </ol>
        <p v-else class="status-cycle">
          轮次 <code>{{ live.cycle_id }}</code>
        </p>

        <button class="button primary" type="button" :disabled="refreshing" @click="refresh">
          <RefreshCw :size="15" :class="{ spinning: refreshing }" aria-hidden="true" />
          {{ refreshing ? '正在更新' : '立即更新实测与预测' }}
        </button>
      </section>

      <Notice v-if="notice" kind="good">{{ notice }}</Notice>
      <Notice v-if="live.refreshing" kind="loading">
        {{ phaseText }}。{{ fresh ? '更新期间可以继续查看尚未过期的上一轮结果。' : '' }}
      </Notice>
      <Notice v-if="live.refresh?.phase === 'failed'" kind="error">
        {{ live.refresh.error }}。
        {{ live.usable ? '当前显示上一轮尚未过期的结果。' : '数据恢复后将重新生成预测。' }}
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
        <div class="stat-row">
          <StatCard
            label="北京覆盖站点实测均值"
            :value="fmt(live.current)"
            unit="μg/m³"
            :icon="Activity"
            :featured="fresh"
            :hint="`实测时刻 ${bjDateTime(live.origin)}`"
          />
          <StatCard
            label="最新实测距现在"
            :value="fmtInt(dataAge)"
            unit="分钟"
            :icon="Clock3"
            hint="官方发布有延迟；超过 3 小时停止发布预测"
          />
          <StatCard
            label="本轮可预测站点"
            :value="fmtInt(live.forecast_stations)"
            :unit="`/ ${live.beijing_stations} 个北京站点`"
            :icon="MapPin"
            hint="起点有实测且过去 72 小时至少 48 小时有效"
          />
          <StatCard
            label="起点天气（模型输入）"
            :value="fmt(startWeather?.temperature_2m)"
            unit="°C"
            :icon="Thermometer"
            :hint="weatherHint"
          />
        </div>

        <Notice v-if="!fresh" kind="warn">
          上一轮预测已经过期或资料正在准备，正在等待新的当前预测。实测超过三小时没有更新时系统会停止发布。
        </Notice>

        <PanelCard
          v-if="fresh"
          kicker="未来六个整点 · 每个整点直接输出"
          :title="`${selectedName}：PM₂.₅ 预测`"
        >
          <template #actions>
            <select v-model="selected" class="select" aria-label="选择预测站点">
              <option value="mean">北京覆盖站点均值（{{ live.forecast_stations }} 站）</option>
              <option
                v-for="station in live.stations"
                :key="station.station_id"
                :value="station.station_id"
                :disabled="!station.available"
              >
                {{ stationOptionText(station) }}
              </option>
            </select>
            <a class="button small" :href="exportHref"><Download :size="14" />导出 CSV</a>
          </template>

          <ol class="strip">
            <li class="strip-now">
              <span class="strip-time">{{ bjTime(forecast.origin) }} 实测</span>
              <strong>{{ fmt(forecast.current) }}</strong>
              <span class="strip-sub">起点</span>
            </li>
            <li v-for="point in forecast.points" :key="point.target">
              <i class="strip-level" :style="{ background: pmColor(point.prediction) }"></i>
              <span class="strip-time">{{ bjTime(point.target) }} · +{{ point.horizon }} h</span>
              <strong>{{ fmt(point.prediction) }}</strong>
              <span class="strip-sub">
                {{ point.lower === null ? '无区间' : `${fmt(point.lower)}–${fmt(point.upper)}` }}
              </span>
              <span v-if="point.method === 'recursive_extension'" class="tag warn">递推延伸</span>
            </li>
          </ol>

          <Chart :option="forecastOption" height="340px" label="北京未来六个整点 PM2.5 预测与历史实测" />

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
                    <th class="num">80% 区间</th>
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
                      {{ point.lower === null ? '—' : `${fmt(point.lower)}–${fmt(point.upper)}` }}
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
            6 小时后预计 {{ fmt(lastPoint?.prediction) }} μg/m³。
            历史测试显示，高浓度和浓度突变时区间覆盖不足。<a href="#online">查看在线核验 →</a>
          </template>
        </PanelCard>

        <div v-if="fresh" class="grid-2">
          <PanelCard
            kicker="最新实测 · 点击站点切换预测"
            title="北京各站点当前浓度"
            :note="`${bjDateTime(live.origin)} 的实测；灰色点表示该时刻无实测。`"
          >
            <Chart
              :option="mapOption"
              height="330px"
              label="北京各站点最新 PM2.5 地图"
              @select="onMapSelect"
            />
            <PmLegend />
          </PanelCard>

          <PanelCard kicker="站点状态" title="哪些站点本轮可以预测">
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
                    :class="{
                      selected: station.station_id === selected,
                      clickable: station.available,
                    }"
                    @click="selectStation(station.station_id)"
                  >
                    <td>{{ station.name }} <span class="muted">{{ station.station_id }}</span></td>
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
          </PanelCard>
        </div>

        <div v-if="fresh" class="grid-wide-left">
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

          <PanelCard kicker="天气预报" title="未来六个整点的天气">
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

        <PanelCard kicker="上线后的真实检验" title="等实测到达，再计算误差">
          <template #actions>
            <span class="tag">已匹配 {{ fmtInt(live.online_evaluation?.matched) }} 条</span>
            <span class="tag">等待实测 {{ fmtInt(live.online_evaluation?.pending) }} 条</span>
          </template>
          <p v-if="!live.online_evaluation?.matched" class="panel-text">
            本轮预测已经存档。目标时刻过去、实测到达后才会计算在线误差；目前还没有可以报告的在线误差。
          </p>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>发布后第几个整点</th>
                  <th class="num">已匹配</th>
                  <th class="num">等待实测</th>
                  <th class="num">TCN MAE</th>
                  <th class="num">TCN RMSE</th>
                  <th class="num">基线 RMSE</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in live.online_evaluation.by_horizon" :key="row.horizon">
                  <td>第 {{ row.horizon }} 个</td>
                  <td class="num">{{ fmtInt(row.n) }}</td>
                  <td class="num">{{ fmtInt(row.pending) }}</td>
                  <td class="num">{{ fmt(row.mae, 2) }}</td>
                  <td class="num strong">{{ fmt(row.rmse, 2) }}</td>
                  <td class="num">{{ fmt(row.baseline_rmse, 2) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <template #note>
            {{ live.online_evaluation?.note }}
            <a href="#online">查看逐日、分站点、分浓度的完整核验 →</a>
          </template>
        </PanelCard>

        <PanelCard kicker="数据从哪里来" title="这一轮预测经过的流水线">
          <ol class="pipeline">
            <li>
              <span class="pipe-step">1 · 采集</span>
              <strong>{{ live.air_sources.map(source => source.name).join(' + ') }}</strong>
              <span>{{ live.weather_source.name }}</span>
              <small>采集于 {{ bjDateTime(live.source_fetched_at) }}</small>
            </li>
            <li>
              <span class="pipe-step">2 · HDFS</span>
              <strong>原始文件与清单入库</strong>
              <span><code>live_v1/cycles/{{ live.cycle_id }}</code></span>
            </li>
            <li>
              <span class="pipe-step">3 · Spark</span>
              <strong>Spark {{ live.spark_version }} 清洗与融合</strong>
              <span>补齐小时网格、合并天气，构建 {{ live.history_hours }} 小时窗口</span>
            </li>
            <li>
              <span class="pipe-step">4 · GPU 推理</span>
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
          <template #note>
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
            ·
            <a :href="live.weather_source.url" target="_blank" rel="noreferrer">
              天气接口说明<ArrowUpRight :size="12" />
            </a>
          </template>
        </PanelCard>

        <div class="method-note">
          <Info :size="16" aria-hidden="true" />
          <p>{{ live.method_note }} {{ live.accuracy_note }}</p>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
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

.status-cycle {
  font-size: 12px;
  color: var(--ink-3);
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

/* 未来六个整点的横向卡片：第一张是起点实测 */
.strip {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
  margin: 0 0 14px;
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

.strip li.strip-now {
  background: var(--surface);
  border-style: dashed;
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
  font-size: 24px;
  font-weight: 650;
  line-height: 1.25;
}

.strip-sub {
  font-size: 12px;
  color: var(--ink-2);
  font-variant-numeric: tabular-nums;
}

.strip .tag {
  align-self: flex-start;
  margin-top: 4px;
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
    grid-template-columns: repeat(4, minmax(0, 1fr));
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

@media (max-width: 600px) {
  .strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
