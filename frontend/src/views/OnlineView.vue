<script setup>
/*
 * 在线核验页（第三代）。
 * 数据：/api/live/evaluation（按筛选条件统计已发布预测与随后实测的配对）、
 *       /api/live/meta（站点名单）、/api/live/model（2025 年独立历史测试报告）。
 * 规则：在线误差只来自真实发布、随后实测到达的预测，不用历史回放填充；
 *       不同模型版本（checkpoint）分开统计；历史测试结果单独成节，不与在线误差混在一起。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Download, Gauge, RefreshCw, Target, TrendingDown } from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import StatCard from '../components/StatCard.vue'
import { api, apiHref } from '../lib/api'
import {
  beijingDay,
  bjDateTime,
  fmt,
  fmtDuration,
  fmtInt,
  fmtPercent,
} from '../lib/format'
import { regimeNames } from '../lib/labels'
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
const report = ref(null)
const error = ref('')
const busy = ref(false)

const start = ref(beijingDay(-13))
const end = ref(beijingDay(0))
const station = ref('')
const horizon = ref('')
const checkpoint = ref('')

let timer = 0

function params() {
  return {
    start: start.value,
    end: end.value,
    station_id: station.value,
    horizon: horizon.value,
    checkpoint: checkpoint.value,
  }
}

async function load() {
  busy.value = true
  try {
    const [evaluation, meta, model] = await Promise.all([
      api('live/evaluation', params()),
      api('live/meta'),
      api('live/model'),
    ])
    result.value = evaluation
    liveMeta.value = meta
    report.value = model
    error.value = ''
  } catch (reason) {
    error.value = reason.message
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  load()
  // 实测陆续到达，每 30 秒自动更新一次统计
  timer = setInterval(load, 30000)
})

onBeforeUnmount(() => clearInterval(timer))

const exportHref = computed(() => apiHref('live/evaluation/export', params()))

const summary = computed(() => result.value?.summary || {})
const collection = computed(() => result.value?.collection || {})

const stationNames = computed(() => {
  const names = {}
  for (const item of liveMeta.value?.stations || []) {
    names[item.station_id] = item.name
  }
  return names
})

function stationLabel(stationId) {
  const name = stationNames.value[stationId]
  return name ? `${name}（${stationId}）` : stationId
}

function modelLabel(model) {
  const name = model.model_name || '旧版 72 小时 TCN（无区间）'
  return `${name} · ${model.checkpoint_sha256.slice(0, 8)} · ${model.stored} 条`
}

function percentValue(ratio) {
  return ratio === null || ratio === undefined ? null : fmt(ratio * 100)
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
  const values = days.map(row => (row.coverage === null ? null : row.coverage * 100))
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

const testRuns = computed(() => report.value?.runs || null)

// 历史测试：加入未来天气 vs 仅过去天气 vs 持续性基线，按距实测的小时数
const offlineOption = computed(() => {
  const runs = testRuns.value
  if (!runs) {
    return null
  }
  const future = runs.future_weather.test.by_horizon
  const history = runs.history_only.test.by_horizon
  const base = baseOption()
  return {
    ...base,
    legend: legend(['加入未来天气', '仅过去天气', '持续性基线']),
    tooltip: { ...base.tooltip, formatter: categoryTooltip({ digits: 2 }) },
    xAxis: categoryAxis(future.map(row => `+${row.horizon} h`)),
    yAxis: valueAxis('RMSE μg/m³'),
    series: [
      lineSeries({
        name: '加入未来天气',
        data: future.map(row => row.rmse),
        color: palette.green,
        width: 2.5,
        points: true,
      }),
      lineSeries({
        name: '仅过去天气',
        data: history.map(row => row.rmse),
        color: palette.blue,
        points: true,
      }),
      lineSeries({
        name: '持续性基线',
        data: future.map(row => row.baseline_rmse),
        color: roleColors.baseline,
        dashed: true,
      }),
    ],
  }
})

// +6 小时的几个关键子集，用于说明区间在困难情形下的不足
const h6 = computed(() => {
  const test = testRuns.value?.future_weather.test
  if (!test) {
    return null
  }
  return {
    city: test.city_by_horizon?.[5],
    high: test.regimes.pm_ge75[5],
    abrupt: test.regimes.abrupt_ge20[5],
  }
})

const worstCases = computed(() => testRuns.value?.future_weather.worst_test_h6.slice(0, 8) || [])
</script>

<template>
  <div class="stack">
    <Notice v-if="error" kind="error">{{ error }}</Notice>

    <PanelCard kicker="筛选" title="选择要核验的预测">
      <template #actions>
        <button class="button small" type="button" :disabled="busy" @click="load">
          <RefreshCw :size="14" :class="{ spinning: busy }" />
          {{ busy ? '正在加载' : '刷新统计' }}
        </button>
      </template>
      <div class="toolbar">
        <label class="field">
          目标开始日期
          <input v-model="start" type="date" />
        </label>
        <label class="field">
          目标结束日期
          <input v-model="end" type="date" />
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
        <label class="field wide">
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
        <button class="button primary" type="button" :disabled="busy" @click="load">应用筛选</button>
        <a class="button" :href="exportHref"><Download :size="14" />导出明细</a>
      </div>
      <template #note>
        按目标时刻的日期筛选，每次最多 90 天。同一模型、站点、目标时刻和提前整点只取最后发布的一版；
        不同模型版本分开统计。
      </template>
    </PanelCard>

    <Notice v-if="!result && !error" kind="loading">正在读取在线核验记录…</Notice>

    <template v-if="result">
      <div class="stat-row">
        <StatCard
          label="已到达实测的预测"
          :value="fmtInt(summary.n)"
          unit="条"
          :icon="Target"
          featured
          :hint="`另有 ${fmtInt(summary.pending)} 条在等待实测`"
        />
        <StatCard
          label="在线 RMSE"
          :value="fmt(summary.rmse, 2)"
          unit="μg/m³"
          :icon="Gauge"
          :hint="`MAE ${fmt(summary.mae, 2)} · 平均偏差 ${fmt(summary.bias, 2)}`"
        />
        <StatCard
          label="持续性基线 RMSE"
          :value="fmt(summary.baseline_rmse, 2)"
          unit="μg/m³"
          :icon="TrendingDown"
          :hint="`模型相对基线改善 ${fmtPercent(summary.rmse_skill)}（负数表示比基线差）`"
        />
        <StatCard
          label="80% 区间实际覆盖率"
          :value="percentValue(summary.coverage)"
          unit="%"
          :hint="`${fmtInt(summary.interval_n)} 条有区间 · 平均宽度 ${fmt(summary.mean_width)} μg/m³`"
        />
      </div>

      <PanelCard kicker="连续运行积累" title="样本是否足以判断稳定精度">
        <template #actions>
          <span class="tag" :class="collection.mature ? 'good' : 'warn'">
            {{ collection.mature ? '已达到一周覆盖条件' : '仍在积累样本' }}
          </span>
        </template>
        <div class="progress-grid">
          <div>
            <div class="progress-label">
              <span>连续发布时长</span>
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
        <p class="panel-text">
          首次发布 {{ bjDateTime(collection.first_issue) }}，
          最近发布 {{ bjDateTime(collection.last_issue) }}，
          共覆盖 {{ fmtInt(collection.observed_origin_hours) }} 个实测起点小时。
          服务停止或电脑休眠期间不会采集；重新启动后会继续保存和核验。
        </p>
        <Notice v-if="!summary.n" kind="info" class="gap">
          当前筛选下还没有到达的真实目标值。预测已经存档，实测到达后自动更新；不会用历史回放填充在线样本。
        </Notice>
        <template #note>{{ result.note }}</template>
      </PanelCard>

      <div class="grid-2">
        <PanelCard kicker="逐日" title="模型与基线的每日误差" note="RMSE 越低越好；样本少时日间波动大。">
          <Chart :option="dayErrorOption" height="260px" label="在线 TCN 与持续性基线逐日 RMSE" />
        </PanelCard>
        <PanelCard
          kicker="逐日"
          title="实测落在 80% 区间内的比例"
          note="名义 80% 不等于实际保证；没有区间的旧模型不计入覆盖率。"
        >
          <Chart :option="coverageOption" height="260px" label="在线预测区间每日实际覆盖率" />
        </PanelCard>
      </div>

      <PanelCard kicker="按提前量" title="预测越远，误差如何变化">
        <div class="table-wrap">
          <table>
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

      <div class="grid-2">
        <PanelCard
          kicker="按浓度情形"
          title="哪些情况最难预测"
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

        <PanelCard kicker="按站点" title="各站点误差（从大到小）">
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

      <PanelCard kicker="失败案例" title="误差最大的真实预测（最多 20 条）">
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
                <td>{{ stationLabel(row.station_id) }}</td>
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
      v-if="report?.ready && testRuns"
      kicker="另一类证据：2025 年独立历史测试（与上方在线记录分开统计）"
      title="加入未来天气预报，预测是否更准"
    >
      <template #actions>
        <span class="tag">同条件 GPU 对照实验</span>
      </template>
      <p class="panel-text">
        训练 2024 年 1—8 月，选模 9—10 月，区间校准 11—12 月，最终测试 2025 年全年；
        训练起点 {{ fmtInt(report.samples.train) }} 个，测试起点 {{ fmtInt(report.samples.test) }} 个。
        两组模型使用相同的数据切分和历史输入，只改变是否读取未来天气。
      </p>
      <Chart :option="offlineOption" height="280px" label="仅过去天气与加入未来天气的各时长 RMSE" />
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>距实测</th>
              <th class="num">仅过去天气 RMSE</th>
              <th class="num">加入未来天气 RMSE</th>
              <th class="num">持续性基线 RMSE</th>
              <th class="num">区间实际覆盖率</th>
              <th class="num">平均区间宽度</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in testRuns.future_weather.test.by_horizon"
              :key="row.horizon"
            >
              <td>+{{ row.horizon }} h</td>
              <td class="num">{{ fmt(testRuns.history_only.test.by_horizon[index].rmse, 2) }}</td>
              <td class="num strong">{{ fmt(row.rmse, 2) }}</td>
              <td class="num">{{ fmt(row.baseline_rmse, 2) }}</td>
              <td class="num">{{ fmtPercent(row.coverage) }}</td>
              <td class="num">{{ fmt(row.mean_width) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="h6?.city" class="panel-text gap">
        北京覆盖站点均值单独校准：+6 h 共 {{ fmtInt(h6.city.n) }} 个完整小时，区间实际覆盖
        {{ fmtPercent(h6.city.coverage) }}，平均宽度 {{ fmt(h6.city.mean_width) }} μg/m³。
      </p>
      <Notice v-if="h6" kind="warn" class="gap">
        总体覆盖率不代表所有情形：+6 h 高浓度子集的实际覆盖率只有 {{ fmtPercent(h6.high.coverage) }}，
        浓度突变子集 {{ fmtPercent(h6.abrupt.coverage) }}；高浓度子集模型 RMSE
        {{ fmt(h6.high.rmse, 2) }}，持续性基线 {{ fmt(h6.high.baseline_rmse, 2) }}。这些情况仍需改进。
      </Notice>
      <details class="more">
        <summary>查看历史测试的浓度分组与最大误差案例</summary>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>+6 h 实测分组</th>
                <th class="num">样本</th>
                <th class="num">仅过去天气 RMSE</th>
                <th class="num">加入未来天气 RMSE</th>
                <th class="num">基线 RMSE</th>
                <th class="num">区间覆盖率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(group, key) in testRuns.future_weather.test.regimes" :key="key">
                <td>{{ regimeNames[key] }}</td>
                <td class="num">{{ fmtInt(group[5].n) }}</td>
                <td class="num">{{ fmt(testRuns.history_only.test.regimes[key][5].rmse, 2) }}</td>
                <td class="num strong">{{ fmt(group[5].rmse, 2) }}</td>
                <td class="num">{{ fmt(group[5].baseline_rmse, 2) }}</td>
                <td class="num">{{ fmtPercent(group[5].coverage) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="table-wrap gap">
          <table>
            <thead>
              <tr>
                <th>2025 年起点</th>
                <th>站点</th>
                <th class="num">+6 h 预测</th>
                <th class="num">+6 h 实测</th>
                <th class="num">绝对误差</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in worstCases" :key="`${row.station_id}-${row.origin}`">
                <td>{{ row.origin.replace('T', ' ') }}:00</td>
                <td>{{ stationLabel(row.station_id) }}</td>
                <td class="num">{{ fmt(row.prediction) }}</td>
                <td class="num">{{ fmt(row.actual) }}</td>
                <td class="num strong">{{ fmt(row.absolute_error) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
      <template #note>
        {{ report.gpu.device }} · PyTorch {{ report.gpu.pytorch }} ·
        峰值利用率 {{ fmt(report.gpu.peak_util_percent, 0) }}% ·
        训练与评估耗时 {{ fmtDuration(report.gpu.seconds) }}。天气使用
        <a href="https://open-meteo.com/en/docs/previous-runs-api" target="_blank" rel="noreferrer">
          GFS 固定提前 24 小时预报</a>。
      </template>
    </PanelCard>
  </div>
</template>

<style scoped>
.toolbar .field.wide {
  flex-basis: 300px;
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

.gap {
  margin-top: 12px;
}

@media (max-width: 900px) {
  .progress-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
