<script setup>
/*
 * 应用外壳：左侧按实时、历史、资料分组的导航、顶栏和页面标题区。
 * 路由用地址栏的 # 部分（如 #live），不引入路由库；默认页面是实时预测。
 * pages 数组是页面目录：新增页面只需在 views/ 写组件并在这里登记。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  BadgeCheck,
  Clock3,
  Database,
  FileText,
  History,
  Map as MapIcon,
  Menu,
  Radio,
  Server,
  Wind,
  X as CloseMenu,
} from '@lucide/vue'
import { api } from './lib/api'
import { bjFull } from './lib/format'
import LiveView from './views/LiveView.vue'
import AchievementsView from './views/AchievementsView.vue'
import WeatherEvaluationView from './views/WeatherEvaluationView.vue'
import OnlineView from './views/OnlineView.vue'
import StationView from './views/StationView.vue'
import OverviewView from './views/OverviewView.vue'
import AnalysisView from './views/AnalysisView.vue'
import ForecastView from './views/ForecastView.vue'
import ModelsView from './views/ModelsView.vue'
import QualityView from './views/QualityView.vue'
import SystemView from './views/SystemView.vue'

const groups = [
  { id: 'live', name: '实时' },
  { id: 'research', name: '历史' },
  { id: 'evidence', name: '资料' },
]

const pages = [
  {
    id: 'live',
    group: 'live',
    name: '实时预测',
    icon: Radio,
    view: LiveView,
    description: '定位或选择北京监测站，查看该站最新实测和接下来六个整点的 PM₂.₅ 预测。',
  },
  {
    id: 'achievements',
    group: 'live',
    name: '项目成果',
    icon: BadgeCheck,
    view: AchievementsView,
    ownHeading: true,
  },
  {
    id: 'online',
    group: 'live',
    parentNavId: 'achievements',
    name: '在线核验',
    view: OnlineView,
    description: '把实际发布的北京单站预测与后来到达的实测逐条匹配。每条样本对应一个站点和一个目标整点。',
  },
  {
    id: 'model-test',
    group: 'live',
    parentNavId: 'achievements',
    name: '实时模型历史测试',
    view: WeatherEvaluationView,
    description: '查看站点 TCN 在 2025 年独立测试中的误差，以及加入未来天气预报带来的变化。',
    related: { href: '#achievements', label: '返回项目成果' },
  },
  {
    id: 'analysis',
    group: 'research',
    name: '规律分析',
    icon: MapIcon,
    tabs: [
      {
        id: 'overview', label: '趋势与相关性', title: '六城浓度趋势与相关性', view: OverviewView,
        description: '比较北京及周边五城的全期月均与所选年日均浓度。六城浓度相关矩阵使用 2015—2025 年全期观测。',
      },
      {
        id: 'patterns', label: '季节与气象', title: '季节规律与气象关联', view: AnalysisView,
        description: '按年份查看城市的月内小时分布、季节均值与气象关联。',
      },
    ],
  },
  {
    id: 'forecast',
    group: 'research',
    name: '预测回放',
    icon: History,
    tabs: [
      {
        id: 'city', label: '北京城市均值', title: '北京城市均值回放', view: ForecastView,
        description: '选择 2024—2025 年的预测起点和模型，比较起点之后六小时的预测、实测和持续性基线。',
        related: { href: '#models?tab=city', label: '查看城市均值回放的模型评估' },
      },
      {
        id: 'station', label: '单个监测站', title: '监测站预测回放', view: StationView,
        props: { section: 'replay' },
        description: '选择六城中的一个站点和 2024—2025 年的预测起点，查看接下来六小时的模型结果与实测。',
        related: { href: '#models?tab=station', label: '查看监测站回放的模型评估' },
      },
    ],
  },
  {
    id: 'models',
    group: 'research',
    parentNavId: 'forecast',
    name: '历史回放模型评估',
    tabs: [
      {
        id: 'city', label: '城市均值回放', title: '北京城市均值回放模型评估', view: ModelsView,
        description: '在同一批北京城市均值样本上比较 Spark 随机森林、梯度提升树和持续性基线。可切换 2025 年独立测试和 2024 年验证。',
        related: { href: '#forecast?tab=city', label: '回放某个历史时刻' },
      },
      {
        id: 'station', label: '监测站回放', title: '监测站回放模型评估', view: StationView,
        props: { section: 'evaluation' },
        description: '比较 TCN、随机森林与持续性基线在单站预测上的误差。可切换北京或六城站点，以及验证集或测试集。',
        related: { href: '#forecast?tab=station', label: '回放某个站点' },
      },
    ],
  },
  {
    id: 'quality',
    group: 'evidence',
    name: '数据来源与质量',
    icon: Database,
    tabs: [
      {
        id: 'coverage', label: '观测覆盖与缺测', title: '历史观测覆盖与缺测', view: QualityView,
        props: { section: 'coverage' },
        description: '查看六城城市小时数据的全期覆盖与源文件缺失。年份筛选只用于逐年逐城明细及北京小时数据导出。',
      },
      {
        id: 'sources', label: '来源与核验', title: '数据来源与清洗核验', view: QualityView,
        props: { section: 'sources' },
        description: '查看城市空气质量、气象和监测站数据来自哪里，以及清洗、抽查和导出后回读的记录。',
      },
    ],
  },
  {
    id: 'system',
    group: 'evidence',
    name: '处理与训练记录',
    icon: Server,
    tabs: [
      {
        id: 'pipeline', label: '数据流水线', title: '数据处理流水线', view: SystemView,
        description: '按步骤查从数据下载、HDFS 存储、Spark 清洗到模型与网页的数据产物。目录规模和组件信息取自项目盘点。',
        related: { href: '#quality?tab=sources', label: '查看原始数据来源' },
      },
      {
        id: 'gpu', label: 'CUDA 训练记录', title: '站点 TCN 的 CUDA 训练记录', view: StationView,
        props: { section: 'training' },
        description: '查看站点 TCN 训练归档中的设备、显存、耗时和每轮验证误差。',
        related: { href: '#models?tab=station', label: '查看监测站回放的模型评估' },
      },
    ],
  },
]

const legacyRoutes = new Map([
  ['stations', ['forecast', 'station']],
  ['overview', ['analysis', 'overview']],
  ['models?tab=weather', ['model-test', '']],
])

const pageId = ref('live')
const tabId = ref('')
const health = ref(null)
const healthError = ref(false)
const navOpen = ref(false)
const navToggle = ref(null)
const now = ref(Date.now())

const current = computed(() => pages.find(page => page.id === pageId.value) || pages[0])
const currentTab = computed(() => current.value.tabs?.find(tab => tab.id === tabId.value) || current.value.tabs?.[0])
const currentGroup = computed(() => groups.find(group => group.id === current.value.group))
const activeNavId = computed(() => current.value.parentNavId || current.value.id)
const parentPage = computed(() => pages.find(page => page.id === current.value.parentNavId))
const related = computed(() => currentTab.value?.related || current.value.related)

function pagesOf(groupId) {
  return pages.filter(page => page.group === groupId && !page.parentNavId)
}

function closeMenu() {
  if (!navOpen.value) return
  navOpen.value = false
  navToggle.value?.focus()
}

function route() {
  const previousPage = pageId.value
  const previousTab = currentTab.value?.id
  const path = location.hash.slice(1)
  const [hash, query] = path.split('?')
  const [page, tab] = legacyRoutes.get(path) || legacyRoutes.get(hash) || [hash, new URLSearchParams(query).get('tab')]
  pageId.value = pages.some(item => item.id === page) ? page : 'live'
  tabId.value = tab || (hash === 'analysis' ? 'patterns' : '')
  document.title = `${currentTab.value?.title || current.value.name} · 北京空气观察`
  navOpen.value = false
  if (pageId.value !== previousPage || currentTab.value?.id !== previousTab) window.scrollTo({ top: 0 })
}

async function checkHealth() {
  try {
    health.value = await api('health')
    healthError.value = false
  } catch {
    healthError.value = true
  }
}

let clockTimer = 0
let healthTimer = 0

onMounted(() => {
  route()
  window.addEventListener('hashchange', route)
  checkHealth()
  healthTimer = setInterval(checkHealth, 30000)
  clockTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  window.removeEventListener('hashchange', route)
  clearInterval(healthTimer)
  clearInterval(clockTimer)
})
</script>

<template>
  <div class="app">
    <aside class="sidebar" @keydown.esc="closeMenu">
      <div class="sidebar-head">
        <a href="#live" class="brand" @click="closeMenu">
          <span class="brand-mark"><Wind :size="22" :stroke-width="1.8" /></span>
          <span class="brand-name">北京空气观察<small>PM₂.₅ 分析与短时预测</small></span>
        </a>
        <button ref="navToggle" class="button mobile-nav-toggle" type="button"
          :aria-expanded="navOpen" aria-controls="main-navigation" @click="navOpen = !navOpen">
          <component :is="navOpen ? CloseMenu : Menu" :size="16" aria-hidden="true" />
          {{ navOpen ? '收起菜单' : '全部页面' }}
        </button>
      </div>

      <nav id="main-navigation" class="nav-groups" :class="{ 'is-open': navOpen }" aria-label="主要导航">
        <div v-for="group in groups" :key="group.id" class="nav-group">
          <div class="nav-group-label">
            <span>{{ group.name }}</span>
          </div>
          <a
            v-for="page in pagesOf(group.id)"
            :key="page.id"
            :href="page.tabs ? `#${page.id}?tab=${page.tabs[0].id}` : `#${page.id}`"
            class="nav-item"
            :class="{ active: activeNavId === page.id }"
            @click="closeMenu"
            :aria-current="current.id === page.id ? 'page' : undefined"
          >
            <component :is="page.icon" :size="17" :stroke-width="1.8" aria-hidden="true" />
            <span>{{ page.name }}</span>
          </a>
          <a v-if="group.id === 'evidence'" href="/docs" class="nav-item" target="_blank" rel="noreferrer" @click="closeMenu">
            <FileText :size="17" :stroke-width="1.8" aria-hidden="true" />
            <span>接口文档</span>
          </a>
        </div>
      </nav>

      <div class="sidebar-foot">
        <div class="service-state">
          <span class="dot" :class="{ bad: healthError, off: !health && !healthError }"></span>
          {{ healthError ? '后端服务无响应' : health ? '后端服务运行中' : '正在连接服务' }}
        </div>
        <p v-if="health && !healthError">
          历史数据 {{ health.data_ready ? '就绪' : '缺失' }} · 模型 {{ health.models_ready ? '就绪' : '缺失' }}
        </p>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div class="breadcrumb">
          <span>{{ currentGroup.name }}</span>
          <span aria-hidden="true">/</span>
          <template v-if="parentPage && !currentTab">
            <a :href="`#${parentPage.id}`">{{ parentPage.name }}</a>
            <span aria-hidden="true" class="breadcrumb-parent-separator">/</span>
          </template>
          <template v-if="currentTab">
            <a :href="`#${current.id}?tab=${current.tabs[0].id}`">{{ current.name }}</a>
            <span aria-hidden="true">/</span>
            <strong>{{ currentTab.label }}</strong>
          </template>
          <strong v-else>{{ current.name }}</strong>
        </div>
        <div class="topbar-right">
          <span class="clock"><Clock3 :size="14" aria-hidden="true" />北京时间 {{ bjFull(now) }}</span>
        </div>
      </header>

      <div class="page">
        <header v-if="!current.ownHeading" class="page-head">
          <h1>{{ currentTab?.title || current.name }}</h1>
          <p>{{ currentTab?.description || current.description }}</p>
          <a v-if="related" class="related-link" :href="related.href">
            {{ related.label }} <span aria-hidden="true">→</span>
          </a>
        </header>

        <nav v-if="current.tabs" class="toolbar section-nav" :aria-label="current.name">
          <a
            v-for="tab in current.tabs"
            :key="tab.id"
            :href="`#${current.id}?tab=${tab.id}`"
            class="button small"
            :aria-current="currentTab?.id === tab.id ? 'page' : undefined"
          >{{ tab.label }}</a>
        </nav>
        <component
          :is="currentTab?.view || current.view"
          :key="`${current.id}/${currentTab?.id || ''}`"
          v-bind="currentTab?.props || {}"
        />

        <footer class="page-foot">
          <span>北京市 PM₂.₅ 时空分析与短时预测系统</span>
          <span>所有时间均为北京时间（UTC+8）</span>
        </footer>
      </div>
    </main>
  </div>
</template>

<style scoped>
.related-link {
  display: inline-block;
  margin-top: 6px;
  font-size: 13px;
}

.breadcrumb a {
  color: var(--ink-2);
}

@media (max-width: 600px) {
  .breadcrumb a, .breadcrumb-parent-separator { display: none; }
}

.section-nav {
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.section-nav .button[aria-current="page"] {
  border-color: var(--brand);
  color: var(--brand-strong);
  background: var(--brand-soft);
}
</style>
