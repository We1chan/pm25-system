<script setup>
import { computed, ref, watch } from 'vue'
import Chart from './Chart.vue'
import Notice from './Notice.vue'
import PanelCard from './PanelCard.vue'
import { apiHref } from '../lib/api'
import { bjDateTime, bjTime, fmt, isNumber } from '../lib/format'
import { axisTime, baseOption, legend, lineSeries, palette, roleColors, timeAxis, timeTooltip, valueAxis } from '../lib/chart'

const props = defineProps({
  title: { type: String, required: true },
  stationName: { type: String, default: '' },
  initial: { type: Object, default: null },
  detail: { type: Object, default: null },
  target: { type: String, default: '' },
  statusLabels: { type: Object, required: true },
  busy: Boolean,
  error: { type: String, default: '' },
})

const selectedTarget = ref('')
const records = computed(() => props.detail?.records || (props.initial ? [props.initial] : []))
watch(() => [props.target, props.initial?.target], () => {
  selectedTarget.value = props.target || props.initial?.target || ''
}, { immediate: true })
watch(records, items => {
  if (items.length && !items.some(item => item.target === selectedTarget.value)) {
    selectedTarget.value = items[0].target
  }
})
const row = computed(() => records.value.find(record => record.target === selectedTarget.value) || records.value[0])
const context = computed(() => props.detail?.forecast)
const delta = computed(() => isNumber(row.value?.actual) ? row.value.prediction - row.value.actual : null)
const baselineGain = computed(() => delta.value === null ? null
  : Math.abs(row.value.baseline - row.value.actual) - Math.abs(delta.value))
const hasBounds = computed(() => isNumber(row.value?.lower) && isNumber(row.value?.upper))
const inBounds = computed(() => hasBounds.value && row.value.actual >= row.value.lower && row.value.actual <= row.value.upper)

function chartOption(series) {
  const base = baseOption()
  return {
    ...base,
    legend: legend(series.map(item => item.name)),
    tooltip: { ...base.tooltip, formatter: timeTooltip() },
    xAxis: timeAxis(),
    yAxis: valueAxis(),
    series,
  }
}

const outcomeOption = computed(() => {
  if (!row.value) return null
  const fields = [
    ['预测', 'prediction', palette.green, false],
    ['实测', 'actual', roleColors.observed, false],
    ['持续性基线', 'baseline', roleColors.baseline, true],
  ]
  if (records.value.some(item => isNumber(item.lower) && isNumber(item.upper))) {
    fields.push(['区间下限', 'lower', palette.blue, true], ['区间上限', 'upper', palette.blue, true])
  }
  return chartOption(fields.map(([name, key, color, dashed]) => lineSeries({
    name, color, dashed, points: true,
    data: records.value.map(item => [axisTime(item.target), item[key] ?? null]),
    markLine: key === 'prediction' ? {
      silent: true, symbol: 'none', label: { show: false },
      data: [{ xAxis: axisTime(row.value.target) }],
    } : undefined,
  })))
})

const historyOption = computed(() => chartOption([lineSeries({
  name: '发布前 PM₂.₅ 实测', color: roleColors.observed,
  data: (context.value?.history || []).map(item => [axisTime(item.ts), item.pm25]),
})]))

const exportHref = computed(() => apiHref('live/export', {
  station_id: row.value?.station_id, cycle_id: row.value?.cycle_id,
}))
</script>

<template>
  <PanelCard :title="title" class="online-case">
    <template #actions>
      <a v-if="context && row" class="button small" :href="exportHref">导出该站本轮预测</a>
    </template>
    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <p v-if="busy && !row" class="panel-text">正在读取本轮记录…</p>
    <p v-else-if="!row && !error" class="panel-text">当前没有符合条件的发布记录。</p>
    <template v-if="row">
      <div class="case-toolbar">
        <strong>{{ stationName || row.station_id }}</strong>
        <label v-if="records.length > 1">
          目标时刻
          <select v-model="selectedTarget" class="select" aria-label="核验目标时刻">
            <option v-if="!selectedTarget" value="" disabled>{{ bjDateTime(row.target) }}</option>
            <option v-for="item in records" :key="item.target" :value="item.target">{{ bjDateTime(item.target) }}</option>
          </select>
        </label>
        <span v-else>{{ bjDateTime(row.target) }}</span>
        <span class="tag">{{ statusLabels[row.status] }}</span>
      </div>
      <p class="case-publication">
        发布于 {{ bjDateTime(row.issued_at) }} · 实测起点 {{ bjDateTime(row.origin) }}
        <span v-if="row.actual_received_at"> · 实测入库 {{ bjDateTime(row.actual_received_at) }}</span>
      </p>
      <div class="case-metrics">
        <div>
          <strong>预测 {{ fmt(row.prediction) }} · 实测 {{ fmt(row.actual) }} μg/m³</strong>
          <span v-if="delta === null">{{ statusLabels[row.status] || '等待实测核验' }}</span>
          <span v-else-if="delta === 0">预测与实测相同</span>
          <span v-else>{{ delta > 0 ? '高估' : '低估' }} {{ fmt(Math.abs(delta)) }} μg/m³</span>
        </div>
        <div>
          <strong>预测区间</strong>
          <span v-if="!hasBounds">该次发布无区间</span>
          <span v-else>
            {{ fmt(row.lower) }}–{{ fmt(row.upper) }} μg/m³
            <template v-if="delta !== null"> · {{ inBounds ? '实测在区间内' : '实测超出区间' }}</template>
          </span>
        </div>
        <div>
          <strong>持续性基线 {{ fmt(row.baseline) }} μg/m³</strong>
          <span v-if="baselineGain === null">等待实测后比较</span>
          <span v-else-if="baselineGain === 0">与基线误差相同</span>
          <span v-else>模型误差{{ baselineGain > 0 ? '少' : '多' }} {{ fmt(Math.abs(baselineGain)) }} μg/m³</span>
        </div>
      </div>
      <Chart :option="outcomeOption" height="270px" label="发布预测、实测、基线与预测区间" />
      <details v-if="context" class="more">
        <summary>查看发布轮次与当时的预测输入</summary>
        <p class="case-publication">轮次 <code>{{ row.cycle_id }}</code></p>
        <Chart v-if="context.history?.length" :option="historyOption" height="230px" label="发布前小时实测走势" />
        <div v-if="context.weather_next?.length" class="table-wrap">
          <table>
            <caption>发布时使用的未来天气</caption>
            <thead><tr><th>时刻</th><th>气温 °C</th><th>湿度 %</th><th>风速 m/s</th><th>降水 mm</th></tr></thead>
            <tbody>
              <tr v-for="item in context.weather_next" :key="item.ts">
                <td>{{ bjTime(item.ts) }}</td><td>{{ fmt(item.temperature_2m) }}</td>
                <td>{{ fmt(item.relative_humidity_2m) }}</td><td>{{ fmt(item.wind_speed_10m) }}</td>
                <td>{{ fmt(item.precipitation) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
      <p v-else-if="detail" class="panel-text">此轮缺少原始输入归档，以上数值来自核验库。</p>
    </template>
  </PanelCard>
</template>

<style scoped>
.case-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
}

.case-toolbar label { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.case-publication { color: var(--ink-3); font-size: 13px; overflow-wrap: anywhere; }
.case-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 12px 0;
}
.case-metrics > div {
  display: grid;
  gap: 3px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  font-size: 13px;
}
.case-metrics span { color: var(--ink-2); }
caption { padding: 6px 0; text-align: left; }
@media (max-width: 650px) {
  .case-metrics { grid-template-columns: minmax(0, 1fr); }
}
</style>
