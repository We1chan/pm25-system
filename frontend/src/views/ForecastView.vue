<script setup>
/*
 * 预测回放页（第一代，北京城市均值）。
 * 数据：/api/meta（可选起点范围与默认起点）、/api/forecast（某一起点的六小时预测与前 48 小时观测）。
 * 预测只用起点及之前的信息；后来的真实值只用于对照，不参与预测。
 * 2024 年是验证期（用于选择模型），2025 年是独立测试期。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { CircleCheck, Download, Info } from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import StatCard from '../components/StatCard.vue'
import { api } from '../lib/api'
import { bjFull, fmt, fmtSigned } from '../lib/format'
import { cityModelNames } from '../lib/labels'
import { loadHistoryMeta } from '../lib/state'
import {
  axisTime,
  baseOption,
  legend,
  lineSeries,
  modelColors,
  roleColors,
  timeAxis,
  timeTooltip,
  valueAxis,
  zoomControls,
} from '../lib/chart'

const meta = ref(null)
const origin = ref('')
const model = ref('best')
const result = ref(null)
const error = ref('')
const busy = ref(false)

const lastPoint = computed(() => result.value?.points.at(-1) || null)

// 自动择优时各时长实际使用的模型可能不同；图中颜色取第一个时长的模型
const usedModel = computed(() => result.value?.points[0]?.model || 'rf')

watch([origin, model, () => meta.value?.models_ready], async ([selectedOrigin, selectedModel, modelsReady], _previous, onCleanup) => {
  let active = true
  onCleanup(() => { active = false })
  if (!modelsReady) return

  error.value = ''
  const [first, last] = meta.value.forecast_range || []
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:00$/.test(selectedOrigin) ||
      (first && selectedOrigin < first) || (last && selectedOrigin > last)) {
    result.value = null
    busy.value = false
    error.value = '请选择可用日期范围内的整点。'
    return
  }

  busy.value = true
  try {
    const forecast = await api('forecast', { origin: selectedOrigin, model: selectedModel })
    if (active) result.value = forecast
  } catch (reason) {
    if (active) {
      result.value = null
      error.value = reason.message
    }
  } finally {
    if (active) busy.value = false
  }
})

onMounted(async () => {
  try {
    const historyMeta = await loadHistoryMeta()
    origin.value = historyMeta.default_origin.replace(' ', 'T').slice(0, 16)
    meta.value = historyMeta
  } catch (reason) {
    error.value = reason.message
  }
})

function exportCsv() {
  if (!result.value) {
    return
  }
  const header = ['预测起点', '目标时刻', '提前小时', '模型', '预测PM2.5', '真实PM2.5', '基线PM2.5']
  const rows = result.value.points.map(point => [
    point.origin,
    point.target,
    point.horizon,
    cityModelNames[point.model],
    point.prediction,
    point.actual ?? '',
    point.baseline,
  ])
  const text = '﻿' + [header, ...rows].map(row => row.join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'beijing_pm25_forecast.csv'
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const option = computed(() => {
  const data = result.value
  if (!data) {
    return null
  }
  const originTime = axisTime(data.origin)
  const start = [originTime, data.current]
  const future = key => [start, ...data.points.map(point => [axisTime(point.target), point[key]])]
  const lastTarget = axisTime(data.points.at(-1).target)
  const base = baseOption()
  return {
    ...base,
    animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    legend: legend(['历史观测', '模型预测', '后续真实值', '持续性基线']),
    grid: { ...base.grid, bottom: 62 },
    tooltip: { ...base.tooltip, formatter: timeTooltip() },
    xAxis: timeAxis(),
    yAxis: valueAxis(),
    // 默认显示最近一天和未来六小时，拖动底部滑块可以看完整 48 小时
    dataZoom: zoomControls(45),
    series: [
      lineSeries({
        name: '历史观测',
        data: data.history.map(point => [axisTime(point.ts), point.pm25]),
        color: roleColors.observed,
        // 用浅色底标出"未来六小时"的区域
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(10, 110, 79, 0.06)' },
          label: { color: roleColors.baseline, fontSize: 11, position: 'insideTop' },
          data: [[{ name: '未来 6 小时', xAxis: originTime }, { xAxis: lastTarget }]],
        },
      }),
      lineSeries({
        name: '模型预测',
        data: future('prediction'),
        color: modelColors[usedModel.value],
        width: 2.5,
        points: true,
        z: 4,
      }),
      lineSeries({
        name: '后续真实值',
        data: future('actual'),
        color: roleColors.observed,
        dashed: true,
        points: true,
        z: 5,
      }),
      lineSeries({
        name: '持续性基线',
        data: future('baseline'),
        color: roleColors.baseline,
        dashed: true,
      }),
    ],
  }
})
</script>

<template>
  <div class="stack">
    <PanelCard title="选择预测起点与模型">
      <div class="toolbar">
        <label class="field">
          预测起点（北京时间）
          <input
            v-model.lazy="origin"
            type="datetime-local"
            :disabled="!meta?.models_ready"
            :min="meta?.forecast_range?.[0]"
            :max="meta?.forecast_range?.[1]"
            step="3600"
          />
        </label>
        <label class="field">
          预测模型
          <select v-model="model" :disabled="!meta?.models_ready">
            <option v-for="(name, id) in cityModelNames" :key="id" :value="id">{{ name }}</option>
          </select>
        </label>
      </div>
      <template #note>
        可选 2024 年（验证期，用于选择模型）和 2025 年（独立测试期）的整点。
        选择起点或模型后，自动读取已计算的回放结果。
      </template>
    </PanelCard>

    <Notice v-if="meta && !meta.models_ready" kind="info">
      模型正在训练：已完成 {{ meta.training.completed || 0 }} / {{ meta.training.total || 24 }} 组实验，完成后可以回放。
    </Notice>
    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <Notice v-if="busy && !result" kind="loading">正在读取六个预测时长的模型输出…</Notice>

    <template v-if="result">
      <div class="stat-row">
        <StatCard
          label="起点观测浓度"
          :value="fmt(result.current)"
          unit="μg/m³"
          :hint="bjFull(result.origin)"
        />
        <StatCard
          label="未来第 6 小时预测"
          :value="fmt(lastPoint?.prediction)"
          unit="μg/m³"
          featured
          :hint="`较起点 ${fmtSigned(lastPoint?.prediction - result.current)} μg/m³`"
        />
        <StatCard
          label="本次回放平均绝对误差"
          :value="fmt(result.window_mae)"
          unit="μg/m³"
          :hint="`${result.actual_points} 个有真实值的预测点`"
        />
        <StatCard
          label="本次回放所属期间"
          :value="result.split === 'test' ? '独立测试期' : '模型验证期'"
          word
          :icon="CircleCheck"
          :hint="result.split === 'test' ? '2025 年，未参与模型选择' : '2024 年，用于选择推荐模型'"
        />
      </div>

      <PanelCard title="起点前 48 小时实测与起点后 6 小时预测">
        <template #actions>
          <span class="replay-loading" role="status">
            <template v-if="busy">
              <span class="spinner" aria-hidden="true"></span>
              正在读取
            </template>
          </span>
          <button class="button small" type="button" :disabled="busy" @click="exportCsv">
            <Download :size="14" />导出 CSV
          </button>
        </template>
        <Chart :option="option" :aria-busy="busy" height="340px" label="北京 PM2.5 历史观测、模型预测、真实值与持续性基线" />
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>提前</th>
                <th>目标时刻</th>
                <th>使用模型</th>
                <th class="num">预测</th>
                <th class="num">真实值</th>
                <th class="num">持续性基线</th>
                <th class="num">绝对误差</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="point in result.points" :key="point.horizon">
                <td><span class="tag">+{{ point.horizon }} h</span></td>
                <td>{{ bjFull(point.target) }}</td>
                <td>{{ cityModelNames[point.model] }}</td>
                <td class="num strong">{{ fmt(point.prediction) }}</td>
                <td class="num">{{ fmt(point.actual) }}</td>
                <td class="num">{{ fmt(point.baseline) }}</td>
                <td class="num">
                  {{ point.actual === null ? '—' : fmt(Math.abs(point.prediction - point.actual)) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <template #note>
          单位 μg/m³。真实值中的缺测保留为空，不参与误差；持续性基线把起点浓度原样延续到未来六小时。
        </template>
      </PanelCard>
    </template>

    <div class="method-note">
      <Info :size="16" aria-hidden="true" />
      <p>{{ meta?.weather_note || '气象采用 ERA5 历史再分析资料。' }}历史回放的成绩不能等同于真实在线预报的精度。</p>
    </div>
  </div>
</template>

<style scoped>
.replay-loading {
  display: inline-flex;
  min-width: 6.5em;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  color: var(--ink-2);
  font-size: 12px;
}
</style>
