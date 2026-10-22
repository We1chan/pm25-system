<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Chart from '../components/Chart.vue'
import { api, fmt, cityNames, colors, baseChart, lineOption } from '../lib/api'
const props = defineProps({ meta: Object, year: String })
const city = ref('beijing'), variable = ref('relative_humidity_2m'), pattern = ref(null), weather = ref(null), trend = ref(null), analysis = ref(null), error = ref(''), busy = ref(true)
let request = 0
async function load() {
  const id = ++request
  busy.value = true; error.value = ''
  try {
    const y = props.year
    const [p, w, t, o] = await Promise.all([api('pattern', { city: city.value, year: y }), api('weather', { city: city.value, year: y, variable: variable.value }), api('trend', { cities: city.value, start: y === 'all' ? '2015-01-01' : `${y}-01-01`, end: y === 'all' ? '2025-12-31' : `${y}-12-31` }), api('overview', { year: y })])
    if (id === request) { pattern.value = p; weather.value = w; trend.value = t; analysis.value = o.analysis }
  } catch (e) { if (id === request) error.value = e.message } finally { if (id === request) busy.value = false }
}
onMounted(load); watch([city, variable, () => props.year], load)
const trendOption = computed(() => lineOption(trend.value?.series || [], { zoom: true }))
const heatOption = computed(() => ({
  ...baseChart, tooltip: { position: 'top', formatter: p => `${p.value[1] + 1} 月 · ${p.value[0]}:00<br/>PM₂.₅ ${fmt(p.value[2])} μg/m³` },
  grid: { top: 10, bottom: 46, left: 42, right: 12 },
  xAxis: { type: 'category', data: Array.from({ length: 24 }, (_, i) => i), axisLabel: { interval: 3, color: '#89948b' }, axisLine: { show: false }, axisTick: { show: false }, name: '时' },
  yAxis: { type: 'category', data: Array.from({ length: 12 }, (_, i) => `${i + 1}月`), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#89948b' } },
  visualMap: { min: 0, max: Math.max(60, ...((pattern.value?.cells || []).map(r => r.value || 0))), calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 11, itemHeight: 150, text: ['高', '低'], textStyle: { color: '#8b968e', fontSize: 10 }, inRange: { color: ['#edf2dd', '#b9cd99', '#6c9e74', '#2d7157'] } },
  series: [{ type: 'heatmap', data: (pattern.value?.cells || []).filter(r => r.value !== null).map(r => [r.hour, r.month - 1, +r.value.toFixed(2)]), itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 2 }, emphasis: { itemStyle: { borderColor: '#4a7257', borderWidth: 2 } } }],
}))
const seasonOption = computed(() => ({ ...baseChart, grid: { top: 25, bottom: 30, left: 50, right: 18 }, xAxis: { ...baseChart.xAxis, type: 'category', data: ['春季', '夏季', '秋季', '冬季'] }, series: [{ type: 'bar', barWidth: '35%', data: ['春季', '夏季', '秋季', '冬季'].map((s, i) => ({ value: pattern.value?.seasons.find(r => r.season === s)?.value, itemStyle: { color: ['#b4c399', '#6f9b83', '#d4b176', '#83a4aa'][i], borderRadius: [5, 5, 0, 0] } })), label: { show: true, position: 'top', formatter: p => fmt(p.value), color: '#65756e' } }] }))
const weatherUnits = { temperature_2m: '°C', relative_humidity_2m: '%', wind_speed_10m: 'm/s' }
const scatterOption = computed(() => ({ ...baseChart, tooltip: { trigger: 'item', formatter: p => `${p.data[2]}<br/>${weather.value?.name}: ${fmt(p.data[0])} ${weatherUnits[variable.value]}<br/>PM₂.₅: ${fmt(p.data[1])} μg/m³` }, xAxis: { ...baseChart.xAxis, type: 'value', name: weatherUnits[variable.value], nameTextStyle: { color: '#89948b' }, splitLine: { show: false } }, yAxis: { ...baseChart.yAxis }, series: [{ type: 'scatter', symbolSize: 4, itemStyle: { color: '#26795e', opacity: .24 }, data: (weather.value?.points || []).map(r => [r.x, r.y, r.ts]) }] }))
const matrixOption = computed(() => {
  const ids = Object.keys(cityNames), entries = []
  for (const row of analysis.value?.city_correlations || []) { entries.push([ids.indexOf(row.city), ids.indexOf(row.other), +row.correlation.toFixed(3)]); if (row.city !== row.other) entries.push([ids.indexOf(row.other), ids.indexOf(row.city), +row.correlation.toFixed(3)]) }
  return { ...baseChart, tooltip: { formatter: p => `${cityNames[ids[p.value[0]]]} × ${cityNames[ids[p.value[1]]]}<br/>Pearson r = ${fmt(p.value[2], 3)}` }, grid: { top: 4, left: 55, right: 20, bottom: 36 }, xAxis: { type: 'category', data: Object.values(cityNames), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { fontSize: 10 } }, yAxis: { type: 'category', data: Object.values(cityNames), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { fontSize: 10 } }, visualMap: { show: false, min: 0, max: 1, inRange: { color: ['#f2f3e7', '#b9c9a2', '#2c765c'] } }, series: [{ type: 'heatmap', data: entries, label: { show: true, formatter: p => fmt(p.value[2], 2), fontSize: 11, color: '#fff' }, itemStyle: { borderWidth: 3, borderColor: '#fff', borderRadius: 3 } }] }
})
</script>
<template>
  <div class="view-toolbar"><div class="select-pills"><button v-for="(name, id) in cityNames" :key="id" :class="{ active: city === id }" @click="city = id">{{ name }}</button></div><span class="quiet">{{ year === 'all' ? '2015—2025 年' : `${year} 年` }} · 有效小时观测</span></div>
  <div v-if="error" class="error-box" role="alert">{{ error }}</div><div v-if="busy" class="page-loader"><span class="spinner"></span> 正在计算分析视图…</div>
  <template v-else>
    <section class="panel"><div class="panel-heading"><div><div class="section-kicker">TIME SERIES</div><h2>{{ cityNames[city] }}的浓度变化</h2></div><span class="subtle-tag">{{ trend?.resolution === 'month' ? '月均浓度' : '日均浓度' }}</span></div><Chart :option="trendOption" height="260px" label="所选城市 PM2.5 时间变化曲线" /></section>
    <div class="two-column-grid"><section class="panel"><div class="panel-heading"><div><div class="section-kicker">MONTH × HOUR</div><h2>污染的时间纹理</h2></div><span class="unit-label">PM₂.₅ · μg/m³</span></div><Chart :option="heatOption" height="300px" label="月份与小时的 PM2.5 浓度热力图" /><div class="panel-note">每个格子代表该月、该小时全部有效观测的平均浓度。</div></section><section class="panel"><div class="panel-heading"><div><div class="section-kicker">SEASONALITY</div><h2>四季之间的差异</h2></div><span class="unit-label">μg/m³</span></div><Chart :option="seasonOption" height="300px" label="春夏秋冬 PM2.5 平均浓度对比" /><div class="panel-note">按日历月份分季，冬季为 12 月、1 月、2 月。</div></section></div>
    <div class="two-column-grid"><section class="panel"><div class="panel-heading"><div><div class="section-kicker">METEOROLOGY</div><h2>气象与污染的关联</h2></div><select v-model="variable" class="compact-select" aria-label="气象分析变量"><option value="relative_humidity_2m">相对湿度</option><option value="wind_speed_10m">风速</option><option value="temperature_2m">气温</option></select></div><div class="correlation-note">Pearson r <strong>{{ fmt(weather?.correlation, 3) }}</strong><span>{{ fmt(weather?.n, 0) }} 个有效小时 · 图中按时间等距抽样</span></div><Chart :option="scatterOption" height="275px" label="气象变量与 PM2.5 浓度散点图" /><div class="panel-note">统计关联不代表因果关系；气象采用历史再分析资料。</div></section><section class="panel"><div class="panel-heading"><div><div class="section-kicker">REGIONAL LINKAGE</div><h2>城市间的共同变化</h2></div><span class="subtle-tag">2015—2025 全时段</span></div><Chart :option="matrixOption" height="306px" label="六个城市 PM2.5 小时浓度相关矩阵" /><div class="panel-note">对每对城市使用同时有观测值的小时计算 Pearson 相关系数。</div></section></div>
  </template>
</template>
