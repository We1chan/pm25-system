<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowDownRight, ArrowUpRight, ArrowRight, Play, Pause, Activity, MapPin, Clock3, Wind, Droplets, Thermometer, Database } from '@lucide/vue'
import * as echarts from 'echarts'
import Chart from '../components/Chart.vue'
import { api, fmt, colors, cityNames, lineOption, baseChart } from '../lib/api'
const props = defineProps({ meta: Object, year: String })
const overview = ref(null), snapshot = ref(null), trend = ref(null), error = ref(''), busy = ref(true)
const snapshotDate = ref('2025-12-30'), hour = ref(12), period = ref('all'), activeCities = ref(['beijing', 'tianjin', 'langfang'])
let playTimer, snapshotRequest = 0, trendRequest = 0, yearRequest = 0
const playing = ref(false)
const beijing = computed(() => snapshot.value?.cities.find(c => c.city_id === 'beijing'))
const ranking = computed(() => [...(snapshot.value?.cities || [])].sort((a, b) => (b.pm25 ?? -1) - (a.pm25 ?? -1)))
const yearLabel = computed(() => overview.value?.year === 'all' ? '2015—2025 年' : `${overview.value?.year || props.year} 年`)
async function loadSnapshot() {
  if (!snapshotDate.value) return
  const request = ++snapshotRequest
  try { const data = await api('snapshot', { time: `${snapshotDate.value}T${String(hour.value).padStart(2, '0')}:00` }); if (request === snapshotRequest) snapshot.value = data } catch (e) { error.value = e.message }
}
async function loadTrend() {
  const request = ++trendRequest
  if (!activeCities.value.length) return
  const year = props.year === 'all' ? '2025' : props.year
  try {
    const data = await api('trend', { cities: activeCities.value.join(','), start: period.value === 'all' ? '2015-01-01' : `${year}-01-01`, end: period.value === 'all' ? '2025-12-31' : `${year}-12-31` })
    if (request === trendRequest) trend.value = data
  } catch (e) { error.value = e.message }
}
async function loadYear() {
  const request = ++yearRequest
  try { const data = await api('overview', { year: props.year }); if (request === yearRequest) { overview.value = data; error.value = '' } }
  catch (e) { if (request === yearRequest) error.value = e.message }
}
onMounted(async () => { await Promise.all([loadYear(), loadSnapshot(), loadTrend()]); busy.value = false })
watch(() => props.year, () => { loadYear(); if (props.year !== 'all') snapshotDate.value = `${props.year}-12-30`; if (period.value !== 'all') loadTrend() })
watch([snapshotDate, hour], loadSnapshot)
watch([period, activeCities], loadTrend, { deep: true })
function toggleCity(id) { if (activeCities.value.includes(id)) { if (activeCities.value.length > 1) activeCities.value = activeCities.value.filter(c => c !== id) } else activeCities.value = [...activeCities.value, id] }
function togglePlay() { playing.value = !playing.value; clearInterval(playTimer); if (playing.value) playTimer = setInterval(() => { hour.value = (hour.value + 1) % 24 }, 1500) }
onBeforeUnmount(() => clearInterval(playTimer))
const mapOption = computed(() => {
  const points = (snapshot.value?.cities || []).map(c => ({ name: cityNames[c.city_id], city_id: c.city_id, value: [props.meta.cities.find(x => x.id === c.city_id).longitude, props.meta.cities.find(x => x.id === c.city_id).latitude, c.pm25] }))
  if (!echarts.getMap('bth-region')) return { ...baseChart, xAxis: { type: 'value', min: 113, max: 120, name: '经度' }, yAxis: { type: 'value', min: 36, max: 43, name: '纬度' }, series: [{ type: 'scatter', data: points.map(p => ({ ...p, value: p.value.slice(0, 2) })), symbolSize: 16, label: { show: true, formatter: '{b}', position: 'top' } }] }
  return {
    tooltip: { trigger: 'item', formatter: p => p.seriesType === 'scatter' ? `${p.name}<br/>PM₂.₅ <b>${fmt(p.value[2])}</b> μg/m³` : p.name },
    geo: { map: 'bth-region', roam: false, layoutCenter: ['47%', '49%'], layoutSize: '97%', silent: true, itemStyle: { areaColor: '#f0f3eb', borderColor: '#d8dfd2', borderWidth: 1 }, regions: [{ name: '北京市', itemStyle: { areaColor: '#dce9dd' } }, { name: '天津市', itemStyle: { areaColor: '#e8ebda' } }], emphasis: { disabled: true } },
    visualMap: { show: false, dimension: 2, min: 0, max: 120, inRange: { color: ['#4a987a', '#afbc76', '#d7ad64', '#c97952', '#a3534c'] } },
    series: [{ type: 'scatter', coordinateSystem: 'geo', data: points, symbolSize: v => v[2] === null ? 9 : 12 + Math.min(v[2], 150) / 8, itemStyle: { borderColor: '#fff', borderWidth: 2, opacity: .94, shadowBlur: 9, shadowColor: '#244f3020' }, label: { show: true, position: 'right', formatter: p => `${p.name}  ${fmt(p.value[2], 0)}`, color: '#3d5141', fontSize: 11, backgroundColor: '#ffffffbc', padding: [3, 5], borderRadius: 3 }, emphasis: { scale: 1.3 } }],
  }
})
const trendOption = computed(() => lineOption(trend.value?.series || [], { zoom: true }))
const strongest = computed(() => (overview.value?.analysis.city_correlations || []).filter(r => r.city === 'beijing' && r.other !== 'beijing').sort((a, b) => b.correlation - a.correlation)[0])
</script>
<template>
  <div v-if="error" class="error-box" role="alert">{{ error }}</div>
  <div v-if="busy" class="page-loader"><span class="spinner"></span> 正在读取区域观测…</div>
  <template v-else>
    <section class="kpi-grid">
      <article class="kpi-card featured"><div class="kpi-label"><span>北京 PM₂.₅ 平均浓度</span><Activity :size="16" /></div><div class="kpi-number">{{ fmt(overview?.beijing_mean) }}<small>μg/m³</small></div><div class="kpi-bottom"><span>{{ yearLabel }}</span><span v-if="overview?.yoy_percent !== null" class="change" :class="{ negative: overview?.yoy_percent > 0 }"><component :is="overview?.yoy_percent <= 0 ? ArrowDownRight : ArrowUpRight" :size="13" />{{ fmt(Math.abs(overview?.yoy_percent)) }}% 同比</span></div></article>
      <article class="kpi-card"><div class="kpi-label"><span>北京小时观测覆盖率</span><Database :size="16" /></div><div class="kpi-number">{{ fmt(overview?.coverage * 100) }}<small>%</small></div><div class="mini-progress"><i :style="{ width: `${overview?.coverage * 100}%` }"></i></div><div class="kpi-bottom">缺测保留为空值</div></article>
      <article class="kpi-card"><div class="kpi-label"><span>区域观测城市</span><MapPin :size="16" /></div><div class="kpi-number">06<small>座城市</small></div><div class="kpi-bottom">北京及周边五城 · 小时数据</div></article>
      <article class="kpi-card"><div class="kpi-label"><span>短时预测窗口</span><Clock3 :size="16" /></div><div class="kpi-number">1–6<small>小时</small></div><a href="#forecast" class="kpi-action">进入历史预测回放 <ArrowRight :size="14" /></a></article>
    </section>
    <div class="map-ranking-grid">
      <section class="panel map-panel"><div class="panel-heading"><div><div class="section-kicker">SPATIAL OBSERVATION</div><h2>此刻，区域空气如何？</h2></div><span class="subtle-tag">六城观测</span></div><div class="map-controls"><input type="date" v-model="snapshotDate" min="2015-01-01" max="2025-12-31" aria-label="地图观测日期"><span class="time-stamp">{{ String(hour).padStart(2, '0') }}:00</span><button class="icon-button" :aria-label="playing ? '暂停小时播放' : '播放小时变化'" @click="togglePlay"><component :is="playing ? Pause : Play" :size="14" /></button><input type="range" v-model.number="hour" min="0" max="23" aria-label="地图观测小时"></div><Chart :option="mapOption" height="325px" label="京津冀六城 PM2.5 浓度分布地图" /><div class="map-legend"><span>PM₂.₅ 小时浓度</span><i></i><span>0</span><span>120+</span><small>μg/m³</small><a href="https://geo.datav.aliyun.com/" target="_blank" rel="noreferrer">边界：DataV</a></div></section>
      <section class="panel ranking-panel"><div class="panel-heading"><div><div class="section-kicker">CITY COMPARISON</div><h2>城市浓度对比</h2></div><span class="unit-label">μg/m³</span></div><div class="ranking-time">{{ snapshot?.time.slice(0, 16) }} · 北京时间</div><div class="ranking-list"><div v-for="(city, index) in ranking" :key="city.city_id" class="rank-row"><span class="rank-index">{{ String(index + 1).padStart(2, '0') }}</span><span class="rank-city">{{ cityNames[city.city_id] }}</span><div class="rank-track"><i :style="{ width: city.pm25 === null ? '0%' : `${Math.max(3, city.pm25 / Math.max(100, ranking[0]?.pm25 || 100) * 100)}%`, background: city.city_id === 'beijing' ? '#176e59' : '#b9c9ad' }"></i></div><strong>{{ fmt(city.pm25, 0) }}</strong></div></div><div class="weather-strip"><div><Thermometer :size="15" /><strong>{{ fmt(beijing?.temperature_2m) }}°</strong><span>气温</span></div><div><Droplets :size="15" /><strong>{{ fmt(beijing?.relative_humidity_2m, 0) }}%</strong><span>湿度</span></div><div><Wind :size="15" /><strong>{{ fmt(beijing?.wind_speed_10m) }}</strong><span>风速 m/s</span></div></div><div class="panel-note">北京气象 · ERA5 再分析资料</div></section>
    </div>
    <section class="panel trend-panel"><div class="panel-heading"><div><div class="section-kicker">TEMPORAL TREND</div><h2>{{ period === 'all' ? '十一年的变化，沿时间展开' : `${yearLabel}的浓度变化` }}</h2></div><div class="segmented"><button :class="{ active: period === 'all' }" @click="period = 'all'">十一年月均</button><button :class="{ active: period === 'year' }" @click="period = 'year'">所选年日均</button></div></div><div class="chart-legend"><button v-for="(name, id, index) in cityNames" :key="id" :class="{ muted: !activeCities.includes(id) }" @click="toggleCity(id)"><i :style="{ background: colors[index] }"></i>{{ name }}</button><span class="legend-caption">{{ trend?.start }} — {{ trend?.end }}</span></div><Chart :option="trendOption" height="285px" label="各城市 PM2.5 浓度历史趋势" /><div class="panel-note">均值按有效观测小时加权；曲线保留缺测，可拖动底部时间条查看局部。</div></section>
    <section class="insight-grid"><div><span class="insight-number">01</span><div><h3>区域联动，值得关注</h3><p>北京与{{ cityNames[strongest?.other] || '周边城市' }}的小时浓度相关系数为 <strong>{{ fmt(strongest?.correlation, 2) }}</strong>。<small>2015—2025 年，统计关联不代表因果。</small></p></div></div><div><span class="insight-number">02</span><div><h3>从观测走向预测</h3><p>使用历史污染与气象信息，预测未来六小时。<a href="#models">查看独立测试表现 <ArrowUpRight :size="12" /></a></p></div></div></section>
  </template>
</template>
