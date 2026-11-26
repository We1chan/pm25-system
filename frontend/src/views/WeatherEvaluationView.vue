<script setup>
import { computed, onMounted, ref } from 'vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import { api } from '../lib/api'
import { fmt, fmtDuration, fmtInt, fmtPercent } from '../lib/format'
import { regimeNames } from '../lib/labels'
import { baseOption, categoryAxis, categoryTooltip, legend, lineSeries, palette, roleColors, valueAxis } from '../lib/chart'

const report = ref(null)
const liveCheckpoint = ref('')
const stations = ref([])
const stationNames = computed(() => new Map(stations.value.map(item => [item.station_id, item.name])))

function stationLabel(stationId) {
  const name = stationNames.value.get(stationId)
  return name ? `${name}（${stationId}）` : stationId
}

const error = ref('')
onMounted(async () => {
  try {
    const [model, meta] = await Promise.all([
      api('live/model'),
      api('live/meta').catch(() => null),
    ])
    stations.value = meta?.stations || []
    liveCheckpoint.value = meta?.checkpoint_sha256 || ''
    report.value = model
  } catch (reason) {
    error.value = reason.message
  }
})

const testRuns = computed(() => {
  const runs = report.value?.runs
  return runs?.future_weather?.test && runs?.history_only?.test ? runs : null
})
const reportVersion = computed(() => {
  const checkpoint = report.value?.checkpoint_sha256
  if (!checkpoint) return ''
  if (checkpoint === liveCheckpoint.value) return '与最近一轮实时预测使用相同权重'
  const version = `报告模型 ${checkpoint.slice(0, 8)}`
  return liveCheckpoint.value ? `${version} · 最近实时模型 ${liveCheckpoint.value.slice(0, 8)}` : version
})

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

// +6 小时的历史测试结果和重点样本分组。
const h6 = computed(() => {
  const runs = testRuns.value
  if (!runs) return null

  const test = runs.future_weather.test
  return {
    forecast: test.by_horizon.find(row => row.horizon === 6),
    history: runs.history_only.test.by_horizon.find(row => row.horizon === 6),
    city: test.city_by_horizon?.[5],
    high: test.regimes?.pm_ge75?.[5],
    abrupt: test.regimes?.abrupt_ge20?.[5],
  }
})

const worstCases = computed(() => testRuns.value?.future_weather.worst_test_h6.slice(0, 8) || [])
</script>

<template>
  <div class="stack">
    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <Notice v-else-if="!report" kind="loading">正在读取历史测试结果…</Notice>
    <Notice v-else-if="!report.ready || !testRuns">历史测试报告尚未就绪。</Notice>
    <PanelCard
      v-if="report?.ready && testRuns"
      kicker="2025 年独立历史测试"
      title="加入未来天气预报，预测是否更准"
    >
      <template v-if="reportVersion" #actions>
        <span class="tag">{{ reportVersion }}</span>
      </template>
      <p v-if="h6?.forecast && h6?.history" class="panel-text">
        提前 6 小时预测时，使用未来天气的 TCN 得到的 RMSE 为 <strong>{{ fmt(h6.forecast.rmse, 2) }} μg/m³</strong>，
        仅用历史天气的 TCN 为 {{ fmt(h6.history.rmse, 2) }}，沿用起点实测值的基线为 {{ fmt(h6.forecast.baseline_rmse, 2) }}。
        RMSE 越低，预测整体越接近实测。
      </p>
      <Chart :option="offlineOption" height="280px" label="仅过去天气与加入未来天气的各时长 RMSE" />
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>距预测起点</th>
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
      <Notice v-if="h6?.high && h6?.abrupt" kind="warn" class="gap">
        总体覆盖率不代表所有情形：+6 h 高浓度子集的实际覆盖率只有 {{ fmtPercent(h6.high.coverage) }}，
        浓度突变子集 {{ fmtPercent(h6.abrupt.coverage) }}；高浓度子集模型 RMSE
        {{ fmt(h6.high.rmse, 2) }}，持续性基线 {{ fmt(h6.high.baseline_rmse, 2) }}。这些情况仍需改进。
      </Notice>
      <details class="more">
        <summary>查看测试方法、浓度分组与最大误差案例</summary>
        <p class="panel-text">
          训练使用 2024 年 1—8 月，选模用 9—10 月，区间校准用 11—12 月。独立测试覆盖 2025 年全年。
          训练包含 {{ fmtInt(report.samples.train) }} 个起点，测试包含 {{ fmtInt(report.samples.test) }} 个起点。
          两组模型使用相同的数据切分和历史输入，只改变是否读取未来天气。
        </p>
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
