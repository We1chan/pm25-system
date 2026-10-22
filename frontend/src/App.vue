<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { Wind, LayoutDashboard, ChartNoAxesCombined, ScanLine, FlaskConical, Database, ArrowUpRight, Download, ChevronDown, Leaf } from '@lucide/vue'
import { api } from './lib/api'
import OverviewView from './views/OverviewView.vue'
import AnalysisView from './views/AnalysisView.vue'
import ForecastView from './views/ForecastView.vue'
import ModelsView from './views/ModelsView.vue'
import QualityView from './views/QualityView.vue'
import StationView from './views/StationView.vue'
import LiveView from './views/LiveView.vue'
import OnlineView from './views/OnlineView.vue'
const pages = [
  { id: 'live', name: '实时预测', english: 'LIVE FORECAST', icon: Wind, view: LiveView, title: '现在的北京，接下来的六小时', description: '接入最新空气实测与业务天气资料，生成未来预测，并等待后续实测核验。' },
  { id: 'online', name: '在线核验', english: 'ONLINE VERIFICATION', icon: FlaskConical, view: OnlineView, title: '让每一轮预测，接受实测检验', description: '连续积累真实在线误差，比较站点与时长，检查区间覆盖与浓度突变。' },
  { id: 'stations', name: '站点与 GPU', english: 'STATION LAB', icon: ScanLine, view: StationView, title: '从城市均值，走向每个监测站', description: '保留站点差异，加入 72 小时气象历史，比较 Spark 与 CUDA 模型。' },
  { id: 'overview', name: '区域概览', english: 'OVERVIEW', icon: LayoutDashboard, view: OverviewView, title: '区域空气质量概览', description: '从十一年小时观测中，理解北京与周边城市的污染变化。' },
  { id: 'analysis', name: '时空分析', english: 'EXPLORATION', icon: ChartNoAxesCombined, view: AnalysisView, title: '探索时间、空间与气象', description: '对比城市差异，观察季节规律，寻找污染与气象的关联。' },
  { id: 'forecast', name: '短时预测', english: 'FORECAST', icon: ScanLine, view: ForecastView, title: '看见接下来的六小时', description: '选择历史观测时点，回放模型预测，并与后续真实浓度对比。' },
  { id: 'models', name: '模型评估', english: 'MODELS', icon: FlaskConical, view: ModelsView, title: '让预测经得起比较', description: '独立测试、持续性基线与特征消融，呈现模型实际表现。' },
  { id: 'quality', name: '数据质量', english: 'DATA QUALITY', icon: Database, view: QualityView, title: '每一次分析，都有据可查', description: '查看观测覆盖、缺失日期与数据来源，保留真实数据的边界。' },
]
const pageId = ref(location.hash.slice(1) || 'live'), year = ref('2025'), meta = ref(null), error = ref('')
const current = computed(() => pages.find(p => p.id === pageId.value) || pages[0])
function reloadPage() { window.location.reload() }
function route() { pageId.value = location.hash.slice(1) || 'live'; document.title = `${current.value.name} · 北京空气观察`; window.scrollTo({ top: 0 }) }
let timer
onMounted(async () => {
  route()
  window.addEventListener('hashchange', route)
  try { meta.value = await api('meta') } catch (e) { error.value = e.message }
  timer = setInterval(async () => { if (meta.value && !meta.value.models_ready) meta.value = await api('meta').catch(() => meta.value) }, 15000)
})
onBeforeUnmount(() => { window.removeEventListener('hashchange', route); clearInterval(timer) })
const exportYear = computed(() => year.value === 'all' ? '2025' : year.value)
const exportHref = computed(() => `/api/export?city=beijing&start=${exportYear.value}-01-01&end=${exportYear.value}-12-31`)
</script>
<template>
  <div class="workspace">
    <aside class="sidebar">
      <a href="#overview" class="brand"><span class="brand-symbol"><Wind :size="25" :stroke-width="1.7" /></span><span>北京空气观察<small>BEIJING AIR OBSERVATORY</small></span></a>
      <div class="side-section-label">研究工作台 <span>WORKSPACE</span></div>
      <nav aria-label="主要导航"><a v-for="page in pages" :key="page.id" :href="`#${page.id}`" class="nav-item" :class="{ active: current.id === page.id }" :aria-current="current.id === page.id ? 'page' : undefined"><component :is="page.icon" :size="18" :stroke-width="1.7" /><span>{{ page.name }}</span><span v-if="page.id === 'forecast'" class="nav-badge">1–6 h</span></a></nav>
      <div class="side-study"><div class="study-icon"><Leaf :size="17" /></div><h3>一份关于空气的长期观察</h3><p>北京 · 天津 · 廊坊<br>保定 · 唐山 · 张家口</p><div class="study-foot"><span>{{ ['live','online'].includes(current.id) ? '最新实测' : current.id === 'stations' ? '2022—2025' : '2015—2025' }}</span><span>{{ ['live','online'].includes(current.id) ? '6 小时预测' : current.id === 'stations' ? '4 年站点' : '11 年城市' }}</span></div></div>
      <div class="side-footer"><span class="status-dot"></span> {{ ['live','online'].includes(current.id) ? '实时数据预测环境' : '历史数据研究环境' }}<small>{{ ['live','online'].includes(current.id) ? 'SPARK · TCN · HDFS' : 'SPARK ML · HDFS' }}</small></div>
    </aside>
    <main class="main-shell">
      <header class="topbar"><div class="breadcrumb">研究工作台 <span>/</span> <strong>{{ current.name }}</strong></div><div class="topbar-right"><span class="history-badge"><span class="status-dot"></span> {{ ['live','online'].includes(current.id) ? '实时接入与预测' : '小时历史数据' }}</span><a href="#quality" class="topbar-link">数据说明 <ArrowUpRight :size="13" /></a></div></header>
      <div class="page-wrap">
        <section class="page-heading"><div><div class="eyebrow">BEIJING AIR OBSERVATORY <span>/ {{ current.english }}</span></div><h1>{{ current.title }}</h1><p>{{ current.description }}</p></div><div class="heading-actions"><label v-if="['overview','analysis','quality'].includes(current.id)" class="select-wrap"><span class="sr-only">分析年份</span><select v-model="year" aria-label="分析年份"><option value="all">全部年份</option><option v-for="y in meta?.years.slice().reverse()" :value="String(y)">{{ y }} 年</option></select><ChevronDown :size="14" /></label><a v-if="!['stations','live','online'].includes(current.id)" :href="exportHref" class="button secondary small" :title="`导出${year === 'all' ? 2025 : year}年北京小时数据`"><Download :size="15" /> 导出北京 {{ exportYear }}</a></div></section>
        <div v-if="error" class="error-box" role="alert">{{ error }} <button @click="reloadPage">重新加载</button></div>
        <component v-if="meta" :is="current.view" :meta="meta" :year="year" />
        <div v-else-if="!error" class="page-loader"><span class="spinner"></span> 正在连接观测数据…</div>
        <footer class="page-footer"><span>北京市 PM₂.₅ 时空分析与短时预测系统</span><span>北京时间 UTC+8 <i>·</i> {{ ['live','online'].includes(current.id) ? '实测更新与当前预测' : '历史回放与独立评估' }}</span></footer>
      </div>
    </main>
  </div>
</template>


