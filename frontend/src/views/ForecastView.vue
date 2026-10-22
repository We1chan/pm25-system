<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, ScanLine, Download, Info, CheckCircle2 } from '@lucide/vue'
import Chart from '../components/Chart.vue'
import { api, fmt, models, baseChart } from '../lib/api'
const props = defineProps({ meta: Object })
const origin = ref(props.meta.default_origin.replace(' ', 'T').slice(0, 16)), model = ref('best'), result = ref(null), error = ref(''), busy = ref(false)
async function predict() {
  busy.value = true; error.value = ''; result.value = null
  try { result.value = await api('forecast', { origin: origin.value, model: model.value }) } catch (e) { error.value = e.message } finally { busy.value = false }
}
onMounted(() => { if (props.meta.models_ready) predict() })
const last = computed(() => result.value?.points[5])
const option = computed(() => {
  if (!result.value) return { ...baseChart }
  const r = result.value, n = r.history.length, times = [...r.history.map(p => p.ts), ...r.points.map(p => p.target)]
  const forecast = [...Array(n - 1).fill(null), r.current, ...r.points.map(p => p.prediction)]
  const baseline = [...Array(n - 1).fill(null), r.current, ...r.points.map(p => p.baseline)]
  const actual = [...Array(n - 1).fill(null), r.current, ...r.points.map(p => p.actual)]
  return { ...baseChart, grid: { ...baseChart.grid, top: 25, right: 30, bottom: 36 },
    xAxis: { ...baseChart.xAxis, type: 'category', boundaryGap: false, data: times, axisLabel: { color: '#89948b', formatter: v => v.slice(5, 16) } },
    yAxis: { ...baseChart.yAxis }, tooltip: { ...baseChart.tooltip, valueFormatter: v => `${fmt(v)} μg/m³` },
    series: [
      { name: '历史观测', type: 'line', data: [...r.history.map(p => p.pm25), ...Array(6).fill(null)], showSymbol: false, lineStyle: { color: '#3d7f68', width: 2 }, itemStyle: { color: '#3d7f68' }, areaStyle: { color: '#3d7f680a' } },
      { name: '模型预测', type: 'line', data: forecast, showSymbol: true, symbolSize: 6, itemStyle: { color: '#cf9450', borderColor: '#fff', borderWidth: 1.5 }, lineStyle: { color: '#cf9450', width: 2.8 }, markArea: { silent: true, itemStyle: { color: '#d4bd8d14' }, label: { color: '#b58c52', fontSize: 10, position: 'insideTop' }, data: [[{ name: '未来 6 小时', xAxis: r.origin }, { xAxis: times[times.length - 1] }]] } },
      { name: '后续真实值', type: 'line', data: actual, showSymbol: true, symbolSize: 4, lineStyle: { color: '#7198a4', width: 1.7, type: 'dashed' }, itemStyle: { color: '#7198a4' } },
      { name: '持续性基线', type: 'line', data: baseline, showSymbol: false, lineStyle: { color: '#a7ada3', width: 1, type: 'dotted' }, itemStyle: { color: '#a7ada3' } },
    ],
  }
})
function exportResult() {
  if (!result.value) return
  const rows = [['预测起点', '目标时刻', '预测时长(h)', '模型', '预测PM2.5', '真实PM2.5', '基线PM2.5'], ...result.value.points.map(p => [p.origin, p.target, p.horizon, models[p.model], p.prediction, p.actual ?? '', p.baseline])]
  const csv = '\ufeff' + rows.map(row => row.join(',')).join('\r\n'), url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'beijing_pm25_forecast.csv'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>
<template>
  <section class="forecast-banner"><div class="forecast-emblem"><ScanLine :size="24" :stroke-width="1.5" /></div><div><h3>历史回放预测</h3><p>仅使用预测起点及之前的信息构建特征，后续真实值只用于对照。</p></div><span class="outline-tag">2024 验证 · 2025 测试</span></section>
  <section class="panel forecast-controls"><div class="form-field"><label for="forecast-origin">预测起点 <small>北京时间</small></label><input id="forecast-origin" type="datetime-local" v-model="origin" :min="meta.forecast_range[0]" :max="meta.forecast_range[1]" step="3600"></div><div class="form-field"><label for="forecast-model">预测模型</label><select id="forecast-model" v-model="model"><option v-for="(name, id) in models" :value="id">{{ name }}{{ id === 'best' ? '（按验证集选取）' : '' }}</option></select></div><button class="button primary" @click="predict" :disabled="busy || !meta.models_ready"><span v-if="busy" class="spinner light"></span><ScanLine v-else :size="16" />{{ busy ? '正在读取模型预测' : '运行预测' }}<ArrowRight :size="15" /></button></section>
  <div v-if="!meta.models_ready" class="info-box"><Info :size="17" />模型正在训练：{{ meta.training.completed || 0 }}/{{ meta.training.total || 24 }} 组实验。完成后可进行预测回放。</div>
  <div v-if="error" class="error-box" role="alert">{{ error }}</div>
  <div v-if="busy" class="page-loader"><span class="spinner"></span> 正在读取六个预测时长的模型输出…</div>
  <template v-if="result">
    <section class="kpi-grid forecast-kpis"><article class="kpi-card"><div class="kpi-label">起点观测浓度<span class="small-dot green"></span></div><div class="kpi-number">{{ fmt(result.current) }}<small>μg/m³</small></div><div class="kpi-bottom">{{ result.origin.slice(0, 16) }}</div></article><article class="kpi-card featured"><div class="kpi-label">未来第 6 小时预测<span class="small-dot amber"></span></div><div class="kpi-number">{{ fmt(last?.prediction) }}<small>μg/m³</small></div><div class="kpi-bottom">较当前 {{ last?.prediction >= result.current ? '+' : '' }}{{ fmt(last?.prediction - result.current) }} μg/m³</div></article><article class="kpi-card"><div class="kpi-label">本次窗口平均绝对误差</div><div class="kpi-number">{{ fmt(result.window_mae) }}<small>μg/m³</small></div><div class="kpi-bottom">{{ result.actual_points }} 个有真实值的预测点</div></article><article class="kpi-card"><div class="kpi-label">本次回放所属期间</div><div class="kpi-word">{{ result.split === 'test' ? '独立测试期' : '模型验证期' }}</div><div class="kpi-bottom"><CheckCircle2 :size="13" />{{ result.split === 'test' ? '2025 年未参与模型选择' : '2024 年用于模型选择' }}</div></article></section>
    <section class="panel"><div class="panel-heading"><div><div class="section-kicker">FORECAST REPLAY</div><h2>由过去，向前六小时</h2></div><button class="button text small" @click="exportResult"><Download :size="14" />导出预测</button></div><div class="chart-legend"><span><i style="background:#3d7f68"></i>历史观测</span><span><i style="background:#cf9450"></i>模型预测</span><span><i style="background:#7198a4"></i>后续真实值</span><span><i style="background:#a7ada3"></i>持续性基线</span><span class="legend-caption">前 48 小时观测 + 未来 6 小时</span></div><Chart :option="option" height="340px" label="历史 PM2.5 观测与未来6小时模型预测、真实值及持续性基线对比" /><div class="panel-note">真实值中的缺测保留为空；基线将起点浓度延续到未来六小时。</div></section>
    <section class="panel"><div class="panel-heading"><div><div class="section-kicker">HOURLY DETAILS</div><h2>逐小时预测明细</h2></div><span class="unit-label">浓度与误差单位：μg/m³</span></div><div class="table-scroll"><table><thead><tr><th>预测时长</th><th>目标时刻</th><th>使用模型</th><th class="numeric">预测浓度</th><th class="numeric">真实浓度</th><th class="numeric">绝对误差</th></tr></thead><tbody><tr v-for="point in result.points" :key="point.horizon"><td><span class="hour-pill">+{{ point.horizon }} h</span></td><td>{{ point.target.slice(0, 16) }}</td><td>{{ models[point.model] }}</td><td class="numeric strong-value">{{ fmt(point.prediction) }}</td><td class="numeric">{{ fmt(point.actual) }}</td><td class="numeric">{{ point.actual === null ? '—' : fmt(Math.abs(point.prediction - point.actual)) }}</td></tr></tbody></table></div></section>
  </template>
  <div class="method-note"><Info :size="16" /><p>模型由 Spark ML 训练，页面读取其批量预测结果以支持快速回放。气象输入为 ERA5 历史再分析资料，历史评估不能等同于真实在线预报表现。</p></div>
</template>
