<script setup>
/*
 * 应用外壳：左侧按"三代系统 + 平台"分组的导航、顶栏和页面标题区。
 * 路由用地址栏的 # 部分（如 #live），不引入路由库；默认页面是实时预测。
 * pages 数组是页面目录：新增页面只需在 views/ 写组件并在这里登记。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  BadgeCheck,
  ChartNoAxesCombined,
  Clock3,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  History,
  Map,
  Radio,
  Server,
  Wind,
} from '@lucide/vue'
import { api } from './lib/api'
import { bjFull } from './lib/format'
import LiveView from './views/LiveView.vue'
import OnlineView from './views/OnlineView.vue'
import StationView from './views/StationView.vue'
import OverviewView from './views/OverviewView.vue'
import AnalysisView from './views/AnalysisView.vue'
import ForecastView from './views/ForecastView.vue'
import ModelsView from './views/ModelsView.vue'
import QualityView from './views/QualityView.vue'
import SystemView from './views/SystemView.vue'

const groups = [
  { id: 'live', name: '实时系统', note: '第三代' },
  { id: 'station', name: '站点实验', note: '第二代' },
  { id: 'city', name: '城市研究', note: '第一代' },
  { id: 'platform', name: '平台与架构', note: '大数据组件' },
]

const pages = [
  {
    id: 'live',
    group: 'live',
    name: '实时预测',
    icon: Radio,
    view: LiveView,
    title: '现在的北京，接下来六个整点',
    description: '查看北京监测站点的最新实测、PM₂.₅ 预测与预计范围。',
    scope: [],
  },
  {
    id: 'online',
    group: 'live',
    name: '在线核验',
    icon: BadgeCheck,
    view: OnlineView,
    title: '让每一轮预测接受随后实测的检验',
    description: '预测发布时答案未知；目标时刻过去、真实观测到达后才计算误差。'
      + '这里与历史测试成绩分开统计。',
    scope: ['真实发布记录', '按模型版本分开', '与持续性基线对比'],
  },
  {
    id: 'stations',
    group: 'station',
    name: '站点与 GPU',
    icon: Cpu,
    view: StationView,
    title: '从城市均值走向每个监测站',
    description: '保留每个监测站点各自的差异，加入过去 72 小时天气，'
      + '在同一批样本上比较 Spark 随机森林与 CUDA 时序卷积网络。',
    scope: ['2022—2025 历史', '2022—23 训练 · 2024 验证 · 2025 测试', 'Spark + CUDA'],
  },
  {
    id: 'overview',
    group: 'city',
    name: '区域概览',
    icon: Map,
    view: OverviewView,
    title: '北京与周边五城的空气质量概览',
    description: '基于 2015—2025 年城市小时均值，查看长期变化、某一时刻的区域分布和城市对比。',
    scope: ['2015—2025 历史', '六城城市均值', 'ERA5 再分析气象'],
  },
  {
    id: 'analysis',
    group: 'city',
    name: '时空分析',
    icon: ChartNoAxesCombined,
    view: AnalysisView,
    title: '时间、季节与气象中的污染规律',
    description: '月份 × 小时热力图、四季对比、气象相关和城市间联动。统计关联不代表因果。',
    scope: ['2015—2025 历史', '有效小时观测', 'Pearson 相关'],
  },
  {
    id: 'forecast',
    group: 'city',
    name: '预测回放',
    icon: History,
    view: ForecastView,
    title: '选择历史时刻，回放六小时预测',
    description: '只用起点及之前的信息做预测，再与后来真实发生的浓度对照。'
      + '这是历史回放，不代表现在的预报。',
    scope: ['2024 验证 · 2025 测试', 'Spark ML 批量预测', '北京城市均值'],
  },
  {
    id: 'models',
    group: 'city',
    name: '模型评估',
    icon: FlaskConical,
    view: ModelsView,
    title: '与基线比较，让预测经得起检验',
    description: '按时间划分训练、验证和测试；推荐模型只由 2024 年验证集决定，2025 年测试集只负责最后评价。',
    scope: ['2015—23 训练 · 2024 验证 · 2025 测试', 'Spark ML 随机森林 · 梯度提升树'],
  },
  {
    id: 'quality',
    group: 'city',
    name: '数据质量',
    icon: Database,
    view: QualityView,
    title: '每一个数字都有据可查',
    description: '观测覆盖率、缺失日期、数据来源和清洗核验结果。缺失保留为空，不当作零浓度。',
    scope: ['逐年逐城覆盖', '来源与 SHA-256 清单', 'Spark 清洗核验'],
  },
  {
    id: 'system',
    group: 'platform',
    name: '大数据平台',
    icon: Server,
    view: SystemView,
    title: 'HDFS 与 Spark 实际做了什么',
    description: '数据从下载到网页的完整流水线、HDFS 各目录的真实规模、组件版本和各阶段产物。'
      + '数字来自离线盘点与已保存的报告。',
    scope: ['HDFS 盘点快照', 'Spark 3.5.8 local[4]', 'PyTorch CUDA'],
  },
]

const pageId = ref('live')
const health = ref(null)
const healthError = ref(false)
const now = ref(Date.now())

const current = computed(() => pages.find(page => page.id === pageId.value) || pages[0])
const currentGroup = computed(() => groups.find(group => group.id === current.value.group))

function pagesOf(groupId) {
  return pages.filter(page => page.group === groupId)
}

function route() {
  const hash = location.hash.slice(1)
  pageId.value = pages.some(page => page.id === hash) ? hash : 'live'
  document.title = `${current.value.name} · 北京空气观察`
  window.scrollTo({ top: 0 })
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
    <aside class="sidebar">
      <a href="#live" class="brand">
        <span class="brand-mark"><Wind :size="22" :stroke-width="1.8" /></span>
        <span class="brand-name">北京空气观察<small>PM₂.₅ 分析与短时预测</small></span>
      </a>

      <nav class="nav-groups" aria-label="主要导航">
        <div v-for="group in groups" :key="group.id" class="nav-group">
          <div class="nav-group-label">
            <span>{{ group.name }}</span>
            <small>{{ group.note }}</small>
          </div>
          <a
            v-for="page in pagesOf(group.id)"
            :key="page.id"
            :href="`#${page.id}`"
            class="nav-item"
            :class="{ active: current.id === page.id }"
            :aria-current="current.id === page.id ? 'page' : undefined"
          >
            <component :is="page.icon" :size="17" :stroke-width="1.8" aria-hidden="true" />
            <span>{{ page.name }}</span>
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
          <strong>{{ current.name }}</strong>
        </div>
        <div class="topbar-right">
          <span class="clock"><Clock3 :size="14" aria-hidden="true" />北京时间 {{ bjFull(now) }}</span>
          <a href="/docs" target="_blank" rel="noreferrer"><FileText :size="14" />接口文档</a>
        </div>
      </header>

      <div class="page">
        <header class="page-head">
          <div v-if="current.id !== 'live'" class="page-eyebrow">{{ currentGroup.note }} · {{ currentGroup.name }}</div>
          <h1>{{ current.title }}</h1>
          <p>{{ current.description }}</p>
          <div v-if="current.scope.length" class="scope-chips">
            <span v-for="item in current.scope" :key="item">{{ item }}</span>
          </div>
        </header>

        <component :is="current.view" :key="current.id" />

        <footer class="page-foot">
          <span>北京市 PM₂.₅ 时空分析与短时预测系统</span>
          <span>所有时间均为北京时间（UTC+8）</span>
        </footer>
      </div>
    </main>
  </div>
</template>
