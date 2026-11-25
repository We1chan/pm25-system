<script setup>
/*
 * 在线核验页（第三代）。
 * 数据：/api/live/evaluation（按筛选条件统计已发布预测与随后实测的配对）、
 *       /api/live/meta（站点名单）。
 * 规则：在线误差只来自真实发布、随后实测到达的预测，不用历史回放填充；
 *       不同模型版本（checkpoint）分开统计。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeft, ChevronRight, Download, RefreshCw } from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import OnlineCase from '../components/OnlineCase.vue'
import PanelCard from '../components/PanelCard.vue'
import { api, apiHref } from '../lib/api'
import { verificationHref } from '../lib/liveLinks'
import {
  beijingDay,
  bjDateTime,
  fmt,
  fmtInt,
  fmtPercent,
} from '../lib/format'
import {
  baseOption,
  categoryAxis,
  categoryTooltip,
  legend,
  lineSeries,
  palette,
  referenceLine,
  roleColors,
  valueAxis,
} from '../lib/chart'

const result = ref(null)
const liveMeta = ref(null)
const error = ref('')
const busy = ref(false)
const section = ref('overview')
const caseHeading = ref(null)
const returnSection = ref('records')
const sections = [
  { id: 'overview', label: '核验概览' },
  { id: 'records', label: '核验记录' },
  { id: 'analysis', label: '误差分析' },
]

const initialQuery = new URLSearchParams(location.hash.split('?')[1])
const initialCycle = initialQuery.has('station_id') ? '' : initialQuery.get('cycle_id') || ''
const start = ref(initialCycle ? initialQuery.get('start') || beijingDay(-13) : beijingDay(-13))
const end = ref(initialCycle ? initialQuery.get('end') || beijingDay(0) : beijingDay(0))
const station = ref('')
const horizon = ref('')
const checkpoint = ref('')
const compareCheckpoint = ref('')
const cycleId = ref(initialCycle)
const openedCase = ref(null)
const caseDetail = ref(null)
const caseError = ref('')
const caseBusy = ref(false)
const timelineStatus = ref('')
const timelineOffset = ref(0)
const statusLabels = {
  verified: '已核验',
  waiting: '等待实测',
  scheduled: '目标时刻未到',
  missing: '实测缺失',
}

let timer = 0
let requestId = 0
let caseRequestId = 0

function params() {
  return {
    start: start.value,
    end: end.value,
    station_id: station.value,
    horizon: horizon.value,
    checkpoint: checkpoint.value,
    compare_checkpoint: compareCheckpoint.value,
    cycle_id: cycleId.value.trim(),
  }
}

const applied = ref(params())
const displayed = ref(null)

function applyFilters() {
  applied.value = params()
  timelineOffset.value = 0
  return load()
}

function clearCycle() {
  cycleId.value = ''
  if (initialCycle) {
    start.value = beijingDay(-13)
    end.value = beijingDay(0)
    location.hash = sectionHref(section.value)
  }
  applyFilters()
}

function sectionHref(id) {
  return id === 'overview' ? '#online' : `#online?view=${id}`
}

function recordHref(row, stationId = row.station_id) {
  return `${verificationHref(row.cycle_id, stationId, row.target)}&from=${section.value}`
}

function readRoute() {
  if (location.hash.split('?')[0] !== '#online') return
  const query = new URLSearchParams(location.hash.split('?')[1])
  const view = query.get('view')
  section.value = sections.some(item => item.id === view) ? view : 'overview'
  const from = query.get('from')
  returnSection.value = from === 'analysis' ? 'analysis' : 'records'
  const status = query.get('status')
  if (section.value === 'records' && Object.hasOwn(statusLabels, status)) showTimeline(status)

  const cycle = query.get('cycle_id')
  const stationId = query.get('station_id')
  openedCase.value = cycle && stationId
    ? { cycle_id: cycle, station_id: stationId, target: query.get('target') || '' }
    : null
  if (openedCase.value) nextTick(() => caseHeading.value?.focus({ preventScroll: true }))
  return loadCase()
}

async function loadCase() {
  const selected = openedCase.value
  const id = ++caseRequestId
  caseBusy.value = Boolean(selected)
  caseError.value = ''
  if (caseDetail.value?.cycle_id !== selected?.cycle_id ||
      caseDetail.value?.records?.[0]?.station_id !== selected?.station_id) {
    caseDetail.value = null
  }
  if (!selected) return
  try {
    const detail = await api('live/evaluation/detail', {
      cycle_id: selected.cycle_id, station_id: selected.station_id,
    })
    if (id === caseRequestId) caseDetail.value = detail
  } catch (reason) {
    if (id === caseRequestId) caseError.value = reason.message
  } finally {
    if (id === caseRequestId) caseBusy.value = false
  }
}

async function load() {
  const id = ++requestId
  busy.value = true
  try {
    const filters = applied.value
    const [evaluation, meta] = await Promise.all([
      api('live/evaluation', {
        ...filters, timeline_status: timelineStatus.value, timeline_offset: timelineOffset.value,
      }),
      api('live/meta'),
    ])
    if (id !== requestId) return
    result.value = evaluation
    displayed.value = { ...filters, ...evaluation.filters }
    liveMeta.value = meta
    error.value = ''
    if (!timelineStatus.value) {
      timelineStatus.value = Object.keys(statusLabels).find(key => evaluation.timeline?.[key]?.count) || 'waiting'
    }
    timelineOffset.value = evaluation.timeline?.[timelineStatus.value]?.offset || 0
  } catch (reason) {
    if (id === requestId) error.value = reason.message
  } finally {
    if (id === requestId) busy.value = false
  }
}

onMounted(() => {
  readRoute()
  window.addEventListener('hashchange', readRoute)
  load()
  // 实测陆续到达，每 30 秒自动更新一次统计
  timer = setInterval(() => {
    load()
    if (openedCase.value) loadCase()
  }, 30000)
})

onBeforeUnmount(() => {
  clearInterval(timer)
  window.removeEventListener('hashchange', readRoute)
  requestId += 1
  caseRequestId += 1
})

const exportHref = computed(() => {
  const { compare_checkpoint, ...filters } = displayed.value || applied.value
  return apiHref('live/evaluation/export', {
    ...filters,
    checkpoint: result.value?.checkpoint_sha256 || filters.checkpoint,
  })
})

const summary = computed(() => result.value?.summary || {})
const collection = computed(() => result.value?.collection || {})
const timeline = computed(() => result.value?.timeline?.[timelineStatus.value])
const recordCount = computed(() => Object.keys(statusLabels)
  .reduce((total, key) => total + (result.value?.timeline?.[key]?.count || 0), 0))
const displayedModel = computed(() => {
  const hash = result.value?.checkpoint_sha256
  const model = result.value?.models?.find(item => item.checkpoint_sha256 === hash)
  return model ? modelLabel(model, false) : hash?.slice(0, 8) || '当前线上模型'
})
const observation = computed(() => result.value?.observation_refresh || {})
const observationLabels = {
  collecting: '正在采集实测',
  idle: '暂无到期记录需要补录',
  complete: '实测采集完成',
  partial: '部分实测来源未取得',
  failed: '实测补录未完成',
}

function showTimeline(key) {
  timelineStatus.value = key
  timelineOffset.value = 0
  if (timeline.value?.offset || busy.value) load()
}

function moveTimeline(step) {
  timelineOffset.value = Math.max(0, timelineOffset.value + step * 24)
  load()
}

const stationNames = computed(() => {
  const names = {}
  for (const item of liveMeta.value?.stations || []) {
    names[item.station_id] = item.name
  }
  return names
})

const uncertainty = computed(() => result.value?.uncertainty || null)

const unreliableDays = computed(() =>
  (uncertainty.value?.by_horizon || []).some((row) => !row.reliable),
)

function bootstrapVerdict(row) {
  if (!row.reliable) {
    return '天数不足，仅供参考'
  }
  if (row.gain_ci95[0] == null) {
    return '无法计算相对提升区间'
  }
  if (row.significant) {
    return '显著优于基线'
  }
  return row.gain_ci95[1] < 0 ? '显著低于基线' : '区间含 0，不显著'
}

function stationLabel(stationId) {
  const name = stationNames.value[stationId]
  return name ? `${name}（${stationId}）` : stationId
}

function modelLabel(model, includeCount = true) {
  const name = model.model_name || '旧版 72 小时 TCN（无区间）'
  return `${name} · ${model.checkpoint_sha256.slice(0, 8)}${includeCount ? ` · ${fmtInt(model.stored)} 条` : ''}`
}

function percentValue(ratio) {
  return ratio === null || ratio === undefined ? '—' : fmtPercent(ratio)
}

// 积累进度：连续天数相对建议的 7 天
const dayProgress = computed(() => {
  const days = collection.value.elapsed_days || 0
  const target = collection.value.recommended_days || 7
  return Math.min(1, days / target)
})

const stationRows = computed(() => {
  const rows = [...(result.value?.by_station || [])]
  return rows.sort((a, b) => (b.rmse ?? -1) - (a.rmse ?? -1))
})

const heatmap = computed(() => {
  const cells = result.value?.by_station_horizon || []
  const stations = new Map()
  for (const cell of cells) {
    if (!stations.has(cell.station_id)) stations.set(cell.station_id, new Map())
    stations.get(cell.station_id).set(cell.horizon, cell)
  }
  return { stations, max: Math.max(1, ...cells.map(cell => cell.rmse)) }
})

function selectDay(event) {
  const day = event.name
  if (!(result.value?.by_day || []).some(row => row.key === day && row.n > 0)) return
  start.value = day
  end.value = day
  timelineStatus.value = 'verified'
  applyFilters()
  location.hash = sectionHref('records')
}

function covered(row) {
  if (row.lower === null || row.lower === undefined) {
    return '无区间'
  }
  return row.actual >= row.lower && row.actual <= row.upper ? '是' : '否'
}

function intervalText(row) {
  if (row.lower === null || row.lower === undefined) {
    return '—'
  }
  return `${fmt(row.lower)}–${fmt(row.upper)}`
}

// ---------- 图表 ----------

const dayErrorOption = computed(() => {
  const days = result.value?.by_day || []
  const base = baseOption()
  return {
    ...base,
    legend: legend(['TCN RMSE', '持续性基线 RMSE']),
    tooltip: { ...base.tooltip, formatter: categoryTooltip({ digits: 2 }) },
    xAxis: categoryAxis(days.map(row => row.key)),
    yAxis: valueAxis('RMSE μg/m³'),
    series: [
      lineSeries({
        name: 'TCN RMSE',
        data: days.map(row => row.rmse),
        color: palette.green,
        points: true,
      }),
      lineSeries({
        name: '持续性基线 RMSE',
        data: days.map(row => row.baseline_rmse),
        color: roleColors.baseline,
        dashed: true,
        points: true,
      }),
    ],
  }
})

const coverageOption = computed(() => {
  const days = result.value?.by_day || []
  const base = baseOption()
  const values = days.map(row => (row.coverage == null ? null : row.coverage * 100))
  return {
    ...base,
    tooltip: { ...base.tooltip, formatter: categoryTooltip({ unit: '%', digits: 1 }) },
    xAxis: categoryAxis(days.map(row => row.key)),
    yAxis: valueAxis('实际覆盖率 %', { min: 0, max: 100 }),
    series: [
      lineSeries({
        name: '实测落入区间的比例',
        data: values,
        color: palette.green,
        points: true,
        markLine: referenceLine(80, '名义 80%'),
      }),
    ],
  }
})

</script>

<template>
  <div class="stack verification">
    <template v-if="openedCase">
      <a class="button small return-link" :href="sectionHref(returnSection)">
        <ArrowLeft :size="14" aria-hidden="true" />
        {{ returnSection === 'analysis' ? '返回误差分析' : '返回核验记录' }}
      </a>
      <div ref="caseHeading" class="case-detail" tabindex="-1">
        <OnlineCase
          title="发布轮次核验详情"
          :station-name="stationLabel(openedCase.station_id)"
          :detail="caseDetail"
          :target="openedCase.target"
          :status-labels="statusLabels"
          :busy="caseBusy"
          :error="caseError"
        />
      </div>
    </template>

    <template v-else>
      <PanelCard title="核验范围" class="verification-filters">
        <form class="scope-form" @submit.prevent="applyFilters">
          <div class="scope-fields">
            <label class="field">
              目标开始日期
              <input v-model="start" type="date" required />
            </label>
            <label class="field">
              目标结束日期
              <input v-model="end" type="date" required />
            </label>
            <label class="field">
              站点
              <select v-model="station">
                <option value="">全部北京站点</option>
                <option
                  v-for="item in liveMeta?.stations"
                  :key="item.station_id"
                  :value="item.station_id"
                >
                  {{ item.name }}（{{ item.station_id }}）
                </option>
              </select>
            </label>
            <label class="field">
              发布后第几个整点
              <select v-model="horizon">
                <option value="">全部 1—6</option>
                <option v-for="h in 6" :key="h" :value="h">第 {{ h }} 个整点</option>
              </select>
            </label>
          </div>
          <details class="scope-advanced" :open="Boolean(initialCycle) || undefined">
            <summary>模型版本与发布轮次</summary>
            <div class="scope-fields advanced-fields">
              <label class="field">
                模型版本
                <select v-model="checkpoint">
                  <option value="">当前线上模型</option>
                  <option
                    v-for="model in result?.models"
                    :key="model.checkpoint_sha256"
                    :value="model.checkpoint_sha256"
                  >
                    {{ modelLabel(model) }}
                  </option>
                </select>
              </label>
              <label class="field">
                对照模型
                <select v-model="compareCheckpoint">
                  <option value="">不比较</option>
                  <option v-for="model in result?.models" :key="model.checkpoint_sha256" :value="model.checkpoint_sha256">
                    {{ modelLabel(model) }}
                  </option>
                </select>
              </label>
              <label class="field">
                发布轮次
                <input v-model="cycleId" maxlength="80" placeholder="全部轮次" />
              </label>
            </div>
          </details>
          <div class="scope-actions">
            <p class="panel-text">筛选条件对概览、记录和误差分析同时生效。按目标日期查询，最多 90 天。</p>
            <button class="button primary" type="submit" :disabled="busy">应用筛选</button>
          </div>
        </form>
      </PanelCard>

      <div class="verification-toolbar">
        <nav class="verification-nav" aria-label="在线核验视图">
          <a v-for="item in sections" :key="item.id" :href="sectionHref(item.id)"
            :aria-current="section === item.id ? 'page' : undefined">{{ item.label }}</a>
        </nav>
        <div class="verification-actions">
          <button class="button small" type="button" :disabled="busy" @click="load">
            <RefreshCw :size="14" :class="{ spinning: busy }" aria-hidden="true" />
            {{ busy ? '正在加载' : '刷新' }}
          </button>
          <a v-if="result && !error" class="button small" :href="exportHref">
            <Download :size="14" aria-hidden="true" />导出 CSV
          </a>
        </div>
      </div>

      <p v-if="displayed" class="applied-scope">
        {{ displayed.start }} 至 {{ displayed.end }} ·
        {{ displayed.station_id ? stationLabel(displayed.station_id) : '全部北京站点' }} ·
        {{ displayed.horizon ? `第 ${displayed.horizon} 个整点` : '全部提前量' }} · {{ displayedModel }}
        <span v-if="displayed.cycle_id"> · 轮次 {{ displayed.cycle_id }}</span>
        <button v-if="displayed.cycle_id" class="button small" type="button" :disabled="busy"
          @click="clearCycle">清除轮次筛选</button>
      </p>
      <Notice v-if="error" kind="error">
        {{ error }}<template v-if="result">。下方保留上次成功查询的结果。</template>
      </Notice>
      <Notice v-else-if="!result" kind="loading">正在读取在线核验记录…</Notice>

      <template v-if="result && section === 'overview'">
        <PanelCard title="核验进度">
          <dl class="verification-metrics status-metrics">
            <div v-for="(label, key) in statusLabels" :key="key">
              <dt>{{ label }}</dt>
              <dd>
                <a :href="`#online?view=records&status=${key}`" :aria-label="`查看${label}记录`">
                  {{ fmtInt(result.timeline?.[key]?.count || 0) }}
                  <ChevronRight :size="16" aria-hidden="true" />
                </a>
              </dd>
            </div>
          </dl>
          <p v-if="!recordCount" class="panel-text">当前范围没有发布记录，可扩大日期范围或选择其他模型版本。</p>
        </PanelCard>

        <PanelCard title="已核验预测的精度">
          <p v-if="!summary.n" class="panel-text">暂无预测与实测配对。实测入库后自动计算精度。</p>
          <dl v-else class="verification-metrics">
            <div>
              <dt>模型 RMSE</dt>
              <dd>{{ fmt(summary.rmse, 2) }} <small>μg/m³</small></dd>
              <dd class="metric-note">MAE {{ fmt(summary.mae, 2) }} · 平均偏差 {{ fmt(summary.bias, 2) }}</dd>
            </div>
            <div>
              <dt>持续性基线 RMSE</dt>
              <dd>{{ fmt(summary.baseline_rmse, 2) }} <small>μg/m³</small></dd>
              <dd class="metric-note">基线将起点实测浓度沿用到目标时刻</dd>
            </div>
            <div>
              <dt>RMSE 相对基线改善</dt>
              <dd>{{ percentValue(summary.rmse_skill) }}</dd>
              <dd class="metric-note">负值表示模型误差更大</dd>
            </div>
            <div>
              <dt>80% 区间实际覆盖率</dt>
              <dd>{{ percentValue(summary.coverage) }}</dd>
              <dd class="metric-note">{{ fmtInt(summary.interval_n) }} 条有区间 · 平均宽度 {{ fmt(summary.mean_width) }} μg/m³</dd>
            </div>
          </dl>
        </PanelCard>
        <PanelCard v-if="displayed?.compare_checkpoint" title="同批实测的模型对比">
          <template v-if="result.comparison?.primary.n">
            <div class="table-wrap">
              <table>
                <thead><tr><th>模型版本</th><th class="num">共同样本</th><th class="num">MAE（μg/m³）</th><th class="num">RMSE（μg/m³）</th><th class="num">区间覆盖率</th></tr></thead>
                <tbody>
                  <tr>
                    <td>主模型 {{ result.checkpoint_sha256?.slice(0, 8) }}</td>
                    <td class="num">{{ fmtInt(result.comparison.primary.n) }}</td>
                    <td class="num">{{ fmt(result.comparison.primary.mae, 2) }}</td>
                    <td class="num">{{ fmt(result.comparison.primary.rmse, 2) }}</td>
                    <td class="num">{{ fmtPercent(result.comparison.primary.coverage) }}</td>
                  </tr>
                  <tr>
                    <td>对照 {{ result.comparison.checkpoint_sha256.slice(0, 8) }}</td>
                    <td class="num">{{ fmtInt(result.comparison.comparison.n) }}</td>
                    <td class="num">{{ fmt(result.comparison.comparison.mae, 2) }}</td>
                    <td class="num">{{ fmt(result.comparison.comparison.rmse, 2) }}</td>
                    <td class="num">{{ fmtPercent(result.comparison.comparison.coverage) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="panel-text">比较使用站点、起点、目标时刻、提前量和实测值均一致的记录。</p>
          </template>
          <p v-else class="panel-text">请选择两个不同版本。当前筛选条件下没有可比较的共同实测。</p>
        </PanelCard>
        <PanelCard title="样本积累与实测采集">
          <template #actions>
            <span class="tag" :class="collection.mature ? 'good' : 'warn'">
              {{ collection.mature ? '已达到覆盖建议' : '仍在积累样本' }}
            </span>
          </template>
          <div class="progress-grid">
            <div>
              <div class="progress-label">
                <span>首末发布跨度</span>
                <b>{{ fmt(collection.elapsed_days, 2) }} / {{ collection.recommended_days }} 天</b>
              </div>
              <div class="meter"><i :style="{ width: `${dayProgress * 100}%` }"></i></div>
            </div>
            <div>
              <div class="progress-label">
                <span>起点小时覆盖率（建议不低于 80%）</span>
                <b>{{ fmtPercent(collection.origin_hour_coverage) }}</b>
              </div>
              <div class="meter">
                <i :style="{ width: `${(collection.origin_hour_coverage || 0) * 100}%` }"></i>
              </div>
            </div>
          </div>
          <p v-if="collection.first_issue" class="panel-text">
            首次发布 {{ bjDateTime(collection.first_issue) }}，
            最近发布 {{ bjDateTime(collection.last_issue) }}，
            共覆盖 {{ fmtInt(collection.observed_origin_hours) }} 个起点小时。
            服务停止或电脑休眠期间不会采集；重新启动后会继续保存和核验。
          </p>
          <p v-if="observation.phase" class="panel-text">实测采集：{{ observationLabels[observation.phase] }}</p>
          <p v-if="observation.failed_sources?.length" class="panel-text">
            {{ observation.failed_sources.length }} 份实测文件未取得，后续会继续补录。
          </p>
          <p v-else-if="observation.error" class="panel-text">{{ observation.error }}</p>
          <template #note>{{ result.note }}</template>
        </PanelCard>
      </template>

      <template v-if="result && section === 'records'">
        <PanelCard v-if="result?.timeline" title="发布预测与实测记录">
          <template #actions>
            <a v-if="result.recent_case" class="button small" :href="recordHref(result.recent_case)">
              {{ result.recent_case.status === 'verified' ? '最近一次核验' : '最近一次发布' }}
              <ChevronRight :size="14" aria-hidden="true" />
            </a>
          </template>
          <div class="timeline-filters" role="group" aria-label="按核验状态筛选">
            <button
              v-for="(label, key) in statusLabels"
              :key="key"
              class="button small"
              :class="{ primary: timelineStatus === key }"
              type="button"
              :aria-pressed="timelineStatus === key"
              @click="showTimeline(key)"
            >
              {{ label }} {{ fmtInt(result.timeline[key]?.count) }}
            </button>
          </div>
          <p v-if="!timeline?.records?.length" class="panel-text">当前筛选范围内没有这类记录，可切换核验状态或调整筛选。</p>
          <ol v-else class="verification-timeline">
            <li v-for="row in timeline.records" :key="`${row.cycle_id}-${row.station_id}-${row.target}`">
              <time :datetime="row.target">{{ bjDateTime(row.target) }}</time>
              <a :href="recordHref(row)">{{ stationLabel(row.station_id) }}</a>
              <span>第 {{ row.horizon }} 个整点</span>
              <span>预测 {{ fmt(row.prediction) }} · 实测 {{ fmt(row.actual) }} μg/m³</span>
            </li>
          </ol>
          <div v-if="timeline?.count > 24" class="timeline-filters">
            <button class="button small" type="button" :disabled="busy || !timeline.offset"
              @click="moveTimeline(-1)">上一页</button>
            <span class="panel-text">{{ timeline.offset + 1 }}–{{ timeline.offset + timeline.records.length }} / {{ timeline.count }}</span>
            <button class="button small" type="button" :disabled="busy || timeline.offset + timeline.records.length >= timeline.count"
              @click="moveTimeline(1)">下一页</button>
          </div>
          <template #note>
            每页 24 条。目标时刻过去 24 小时仍无实测时标记为缺失，实测到达后仍可补录。
          </template>
        </PanelCard>

      </template>

      <template v-if="result && section === 'analysis'">
        <Notice v-if="!summary.n" kind="info">当前范围暂无已核验样本。实测入库后可查看误差趋势、分组和案例。</Notice>
        <template v-else>
        <div class="grid-2">
          <PanelCard title="模型与基线的每日误差" note="点击日误差点，将日期筛选切换到当天并打开核验记录。">
            <Chart :option="dayErrorOption" height="260px" label="在线 TCN 与持续性基线逐日 RMSE" @select="selectDay" />
          </PanelCard>
          <PanelCard
            title="预测区间的每日覆盖率"
            note="名义 80% 不等于实际保证；没有区间的旧模型不计入覆盖率。"
          >
            <p v-if="!summary.interval_n" class="panel-text">当前已核验的预测没有可统计的区间。</p>
            <Chart v-else :option="coverageOption" height="260px" label="在线预测区间每日实际覆盖率" />
          </PanelCard>
        </div>

        <PanelCard title="各提前量的预测误差" note="误差与区间宽度单位为 μg/m³。">
          <div class="table-wrap">
            <table class="horizon-table">
              <thead>
                <tr>
                  <th>发布后第几个整点</th>
                  <th class="num">已匹配 / 等待</th>
                  <th class="num">MAE</th>
                  <th class="num">RMSE</th>
                  <th class="num">基线 RMSE</th>
                  <th class="num">区间覆盖率</th>
                  <th class="num">平均区间宽度</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in result.by_horizon" :key="row.key">
                  <td>第 {{ row.key }} 个</td>
                  <td class="num">{{ fmtInt(row.n) }} / {{ fmtInt(row.pending) }}</td>
                  <td class="num">{{ fmt(row.mae, 2) }}</td>
                  <td class="num strong">{{ fmt(row.rmse, 2) }}</td>
                  <td class="num">{{ fmt(row.baseline_rmse, 2) }}</td>
                  <td class="num">{{ fmtPercent(row.coverage) }}</td>
                  <td class="num">{{ fmt(row.mean_width) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </PanelCard>

        <PanelCard title="站点与提前量误差热力图" note="数值为 RMSE（μg/m³）。点开单元格可查看该组误差最大的已核验记录。">
          <p v-if="!heatmap.stations.size" class="panel-text">匹配到实测后显示误差。</p>
          <div v-else class="table-wrap tall">
            <table class="error-heatmap">
              <thead><tr><th>站点</th><th v-for="lead in 6" :key="lead">+{{ lead }} h</th></tr></thead>
              <tbody>
                <tr v-for="[stationId, leads] in heatmap.stations" :key="stationId">
                  <th scope="row">{{ stationLabel(stationId) }}</th>
                  <td v-for="lead in 6" :key="lead">
                    <a v-if="leads.has(lead)"
                      :href="recordHref(leads.get(lead), stationId)"
                      :aria-label="`${stationLabel(stationId)} +${lead} h，RMSE ${fmt(leads.get(lead).rmse, 2)}，查看案例`"
                      :style="{ backgroundColor: `rgba(190, 83, 35, ${0.08 + 0.4 * leads.get(lead).rmse / heatmap.max})` }">
                      {{ fmt(leads.get(lead).rmse, 2) }}
                    </a>
                    <span v-else>—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </PanelCard>

        <div class="grid-2">
          <PanelCard
            title="不同浓度与变化幅度的误差"
            note="按随后的真实浓度、以及真实值相对起点的变化幅度分组，单位 μg/m³。"
          >
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>实测分组</th>
                    <th class="num">样本</th>
                    <th class="num">RMSE</th>
                    <th class="num">基线 RMSE</th>
                    <th class="num">区间覆盖率</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in result.by_regime" :key="row.key">
                    <td>{{ row.key }}</td>
                    <td class="num">{{ fmtInt(row.n) }}</td>
                    <td class="num strong">{{ fmt(row.rmse, 2) }}</td>
                    <td class="num">{{ fmt(row.baseline_rmse, 2) }}</td>
                    <td class="num">{{ fmtPercent(row.coverage) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </PanelCard>

          <PanelCard title="各站点误差（从大到小）" note="RMSE 单位为 μg/m³。">
            <div class="table-wrap tall">
              <table>
                <thead>
                  <tr>
                    <th>站点</th>
                    <th class="num">已匹配</th>
                    <th class="num">RMSE</th>
                    <th class="num">区间覆盖率</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in stationRows" :key="row.key">
                    <td>{{ stationLabel(row.key) }}</td>
                    <td class="num">{{ fmtInt(row.n) }}</td>
                    <td class="num strong">{{ fmt(row.rmse, 2) }}</td>
                    <td class="num">{{ fmtPercent(row.coverage) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </PanelCard>
        </div>

        <PanelCard title="误差最大的预测" note="按绝对误差降序列出最多 20 条已核验记录，浓度和误差单位为 μg/m³。">
          <p v-if="!result.failures.length" class="panel-text">等待当前模型的目标实测到达。</p>
          <div v-else class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>目标时刻</th>
                  <th>站点</th>
                  <th>发布后第几个整点</th>
                  <th class="num">预测</th>
                  <th class="num">实测</th>
                  <th class="num">绝对误差</th>
                  <th class="num">发布时的区间</th>
                  <th>实测落在区间内</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in result.failures"
                  :key="`${row.cycle_id}-${row.station_id}-${row.target}`"
                >
                  <td>{{ bjDateTime(row.target) }}</td>
                  <td><a :href="recordHref(row)">{{ stationLabel(row.station_id) }}</a></td>
                  <td>第 {{ row.horizon }} 个</td>
                  <td class="num">{{ fmt(row.prediction) }}</td>
                  <td class="num">{{ fmt(row.actual) }}</td>
                  <td class="num strong">{{ fmt(row.absolute_error) }}</td>
                  <td class="num">{{ intervalText(row) }}</td>
                  <td>{{ covered(row) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </PanelCard>
        </template>

        <PanelCard
          v-if="uncertainty"
          class="uncertainty-panel"
          kicker="不确定性与重污染"
          title="提升有多可靠，重污染和高值预警表现如何"
          note="按目标自然日整块重采样 2000 次得到 95% 区间；基线为发布时的持续性预测。"
        >
          <Notice v-if="!uncertainty.by_horizon.length" kind="info">
            等待目标时刻的实测到达后才能计算。
          </Notice>
          <template v-else>
            <Notice v-if="unreliableDays" kind="warn">
              覆盖的目标日不足 7 天，区间很宽，只能作为积累进度的参考，不能据此判断模型好坏。
            </Notice>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>提前</th>
                    <th class="num">样本 / 天数</th>
                    <th class="num">模型 RMSE</th>
                    <th class="num">基线 RMSE</th>
                    <th class="num">相对基线提升</th>
                    <th class="num">95% 区间</th>
                    <th>结论</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in uncertainty.by_horizon" :key="row.horizon">
                    <td>第 {{ row.horizon }} 个</td>
                    <td class="num">{{ fmtInt(row.n) }} / {{ fmtInt(row.n_days) }}</td>
                    <td class="num strong">{{ fmt(row.model, 2) }}</td>
                    <td class="num">{{ fmt(row.baseline, 2) }}</td>
                    <td class="num">{{ fmtPercent(row.gain) }}</td>
                    <td class="num">
                      <template v-if="row.gain_ci95[0] != null">{{ fmtPercent(row.gain_ci95[0]) }} ~ {{ fmtPercent(row.gain_ci95[1]) }}</template><template v-else>—</template>
                    </td>
                    <td>{{ bootstrapVerdict(row) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>

          <div v-if="uncertainty.by_horizon.length" class="grid-2 inner-grid">
            <div>
              <h4 class="sub-title">按真实污染档位</h4>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>档位</th>
                      <th class="num">样本</th>
                      <th class="num">模型 MAE</th>
                      <th class="num">基线 MAE</th>
                      <th class="num">相对基线</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in uncertainty.pollution_levels" :key="row.level">
                      <td>{{ row.level }}</td>
                      <td class="num">{{ fmtInt(row.n) }}</td>
                      <td class="num">{{ fmt(row.mae, 2) }}</td>
                      <td class="num">{{ fmt(row.baseline_mae, 2) }}</td>
                      <td class="num">{{ fmtPercent(row.gain) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p class="panel-text small">样本很少的档位（例如严重污染）不具统计意义。</p>
            </div>
            <div>
              <h4 class="sub-title">高值预警（模型对比持续性基线）</h4>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>阈值</th>
                      <th>预测来源</th>
                      <th class="num">召回率</th>
                      <th class="num">精确率</th>
                      <th class="num">误报率</th>
                    </tr>
                  </thead>
                  <tbody>
                    <template v-for="item in uncertainty.alerts" :key="item.threshold">
                      <tr>
                        <td rowspan="2">≥ {{ fmt(item.threshold, 0) }}</td>
                        <td>模型</td>
                        <td class="num strong">{{ fmtPercent(item.model.recall) }}</td>
                        <td class="num">{{ fmtPercent(item.model.precision) }}</td>
                        <td class="num">{{ fmtPercent(item.model.false_alarm_rate) }}</td>
                      </tr>
                      <tr>
                        <td>持续性基线</td>
                        <td class="num">{{ fmtPercent(item.baseline.recall) }}</td>
                        <td class="num">{{ fmtPercent(item.baseline.precision) }}</td>
                        <td class="num">{{ fmtPercent(item.baseline.false_alarm_rate) }}</td>
                      </tr>
                    </template>
                  </tbody>
                </table>
              </div>
              <p class="panel-text small">召回率是实际高值被提前报出的比例；没有事件时显示 —。</p>
            </div>
          </div>
        </PanelCard>
      </template>
    </template>
  </div>
</template>

<style scoped>
.verification {
  gap: 16px;
}

.scope-form {
  display: grid;
  gap: 12px;
}

.scope-fields {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px 14px;
}

.scope-fields .field,
.scope-fields input,
.scope-fields select {
  min-width: 0;
  width: 100%;
}

.scope-advanced {
  border-top: 1px solid var(--border);
  padding-top: 8px;
}

.scope-advanced summary {
  width: fit-content;
  padding-block: 4px;
  color: var(--brand-strong);
  cursor: pointer;
  font-size: 13px;
}

.advanced-fields {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 8px;
}

.scope-actions,
.verification-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 16px;
}

.scope-actions p {
  font-size: 13px;
}

.verification-toolbar {
  border-bottom: 1px solid var(--border-strong);
}

.verification-nav,
.verification-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.verification-nav a {
  display: block;
  padding: 10px 12px;
  border-bottom: 2px solid transparent;
  color: var(--ink-2);
  font-weight: 600;
  text-decoration: none;
}

.verification-nav a:hover,
.verification-nav a[aria-current="page"] {
  color: var(--brand-strong);
  background: var(--brand-soft);
}

.verification-nav a[aria-current="page"] {
  border-bottom-color: var(--brand);
}

.verification-actions {
  padding-bottom: 6px;
}

.applied-scope {
  margin-top: -6px;
  color: var(--ink-2);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.verification-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px 20px;
  margin: 0;
}

.verification-metrics > div {
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.verification-metrics dt,
.verification-metrics small,
.verification-metrics .metric-note {
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 400;
}

.verification-metrics dd {
  margin: 2px 0 0;
  font-size: 24px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.status-metrics a {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  color: var(--brand-strong);
  text-underline-offset: 4px;
}

.status-metrics + p {
  margin-top: 10px;
}

.uncertainty-panel th,
.uncertainty-panel td {
  white-space: nowrap;
}

.inner-grid {
  margin-top: 18px;
}

.sub-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}

.panel-text.small {
  margin-top: 8px;
  font-size: 12px;
}

.horizon-table .num {
  text-align: center;
  white-space: nowrap;
}

.horizon-table .num:last-child {
  padding-inline: 20px;
}

.timeline-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.verification-timeline {
  display: grid;
  gap: 0;
  margin-block: 12px;
  padding: 0 0 0 16px;
  list-style: none;
}

.verification-timeline li {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 10rem) minmax(0, 1fr) minmax(0, 7rem) minmax(0, 13rem);
  gap: 4px 12px;
  padding: 9px 8px 9px 12px;
  border-left: 1px solid var(--border-strong);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.verification-timeline li::before {
  position: absolute;
  top: 16px;
  left: -4px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--brand);
  content: "";
}

.verification-timeline time,
.verification-timeline span { color: var(--ink-2); }
.return-link { justify-self: start; }
.error-heatmap td { text-align: center; }
.error-heatmap th { white-space: nowrap; }
.error-heatmap a {
  display: block;
  min-width: 48px;
  padding: 5px;
  border-radius: var(--radius-sm);
  color: var(--ink);
  text-decoration: underline;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 620px) {
  .verification-timeline li { grid-template-columns: minmax(0, 1fr); }

  .verification :deep(.panel) {
    padding: 16px;
  }

  .verification-nav {
    gap: 4px;
  }

  .verification-nav a {
    padding-inline: 8px;
  }
}

.progress-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  margin-bottom: 14px;
}

.progress-label {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
  font-size: 13px;
  color: var(--ink-2);
}

.progress-label b {
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 900px) {
  .progress-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 740px) {
  .scope-fields,
  .verification-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 380px) {
  .scope-fields {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
