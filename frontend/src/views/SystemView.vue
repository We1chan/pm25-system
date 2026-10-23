<script setup>
/*
 * 大数据平台页：展示 HDFS、Spark、GPU 在本项目里实际承担了什么。
 * 数据：/api/system。它只读取离线生成的 reports/hdfs_inventory.json、已有报告和本地产物元数据，
 *       打开页面不会现场执行 hdfs 或 Spark 命令。
 * 版本号只引用报告中记录的值；报告没有记录的（如 Hadoop、Python）显示"报告未记录"，不在前端补写。
 */
import { computed, onMounted, ref } from 'vue'
import { Cpu, Database, FolderTree, HardDrive, Info, Layers, RefreshCw } from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import StatCard from '../components/StatCard.vue'
import { api } from '../lib/api'
import { bjFull, fmtBytes, fmtInt } from '../lib/format'
import { baseOption, categoryAxis, ink, palette, valueAxis } from '../lib/chart'

const system = ref(null)
const error = ref('')
const busy = ref(false)

// HDFS 各子目录的用途，依据写入这些目录的脚本整理
const hdfsPurpose = {
  raw: '第一代城市版的原始空气质量日文件和 ERA5 气象文件',
  processed: 'Spark 清洗后的城市小时网格与北京特征（Parquet）',
  models: 'Spark MLlib 保存的随机森林、梯度提升树模型管线',
  stations_v2: '站点版：按月封装的全国原始档案、Spark 处理结果与站点模型',
  live_v1: '实时系统每一轮采集的原始资料，按轮次分目录',
  forecast_v3: 'GFS 历史预报存档与未来天气模型的 Spark 训练数据',
}

const pipelineNames = {
  city: '第一代 · 城市版',
  station: '第二代 · 站点版',
  forecast: '第三代 · 未来天气模型',
  live: '实时系统',
  system: '平台',
}

// 教材案例与本项目的对应关系，与 README "系统架构与教材对照"一节一致
const textbook = [
  ['Scrapy', 'requests 下载脚本', '数据源提供 CSV/JSON 和固定接口；直接请求、重试、缓存和哈希清单已能完成采集'],
  ['Kettle', 'Spark 清洗', '在同一处理引擎内完成类型校验、网格、连接和窗口计算，清洗规则可用测试检查'],
  ['MySQL', 'SQLite', '本地演示以查询已发布结果为主，文件数据库便于交付，减少数据库服务维护'],
  ['Scala', 'PySpark', '保留 Spark SQL、DataFrame 和 MLlib 能力，并直接衔接 Python 数据工具与 PyTorch'],
  ['Node.js', 'FastAPI + Vue', 'Python 后端便于读取模型报告和查询库，Vue 负责交互与图表'],
  ['HDFS', 'HDFS', '保留原始层、处理层和模型的实际文件存储与分层验证'],
  ['Spark MLlib', 'Spark MLlib', '真实拟合并保存树模型管线，独立重载后可与网页预测核对'],
]

async function load() {
  busy.value = true
  try {
    system.value = await api('system')
    error.value = ''
  } catch (reason) {
    error.value = reason.message
  } finally {
    busy.value = false
  }
}

onMounted(load)

const inventory = computed(() => system.value?.hdfs_inventory || null)
const entries = computed(() => inventory.value?.entries || [])

const hdfsTotals = computed(() => {
  let files = 0
  let bytes = 0
  for (const entry of entries.value) {
    files += entry.files || 0
    bytes += entry.bytes || 0
  }
  return { files, bytes }
})

const city = computed(() => system.value?.generations.city?.summary || null)
const station = computed(() => system.value?.generations.station?.summary || null)
const forecast = computed(() => system.value?.generations.forecast?.summary || null)

function entry(name) {
  return entries.value.find(item => item.name === name) || null
}

function artifact(path) {
  return system.value?.artifacts.find(item => item.path === path) || null
}

const indexedPredictions = computed(() => {
  const counts = Object.values(station.value?.indexed_predictions || {})
  return counts.reduce((sum, value) => sum + value, 0)
})

const versionRows = computed(() => {
  const versions = system.value?.versions || {}
  const sources = system.value?.version_sources || {}
  const names = {
    spark: 'Apache Spark',
    hadoop: 'Hadoop / HDFS',
    pytorch: 'PyTorch',
    gpu: '显卡',
    python: 'Python',
  }
  return Object.keys(names).map(key => ({
    key,
    name: names[key],
    value: versions[key] ?? null,
    source: sources[key] ? `${sources[key].report} → ${sources[key].field}` : null,
  }))
})

const artifactGroups = computed(() => {
  const groups = []
  for (const item of system.value?.artifacts || []) {
    let group = groups.find(entryGroup => entryGroup.pipeline === item.pipeline)
    if (!group) {
      group = { pipeline: item.pipeline, items: [] }
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups
})

// 流水线六个阶段：每个阶段配上真实规模，数字全部来自 /api/system
const stages = computed(() => {
  const raw = entry('raw')
  const stationHdfs = entry('stations_v2')
  const processed = entry('processed')
  const models = entry('models')
  const download = city.value?.download_summary || {}
  return [
    {
      step: '1 · 采集',
      tool: 'requests 下载脚本',
      lines: [
        `城市 ${fmtInt((download.air?.ok || 0) + (download.weather?.ok || 0))} 份文件`,
        `站点 ${fmtInt(station.value?.source_file_count)} 份逐站文件`,
        '保留来源、时间与 SHA-256 清单',
      ],
    },
    {
      step: '2 · HDFS 存储',
      tool: 'HDFS 原始层',
      lines: [
        `raw/ ${fmtBytes(raw?.bytes)}`,
        `stations_v2/ ${fmtBytes(stationHdfs?.bytes)}`,
        `共 ${fmtInt(hdfsTotals.value.files)} 个文件`,
      ],
    },
    {
      step: '3 · Spark 处理',
      tool: `Spark ${system.value?.versions.spark || ''} · ${city.value?.spark_master || ''}`,
      lines: [
        `城市小时网格 ${fmtInt(city.value?.panel_rows)} 行`,
        `站点小时网格 ${fmtInt(station.value?.grid_hours)} 行`,
        `processed/ ${fmtBytes(processed?.bytes)}`,
      ],
    },
    {
      step: '4 · 建模',
      tool: 'Spark MLlib + PyTorch CUDA',
      lines: [
        `Spark 模型 ${fmtInt(models?.files)} 个文件存于 HDFS`,
        `站点 TCN ${fmtBytes(artifact('models/station_tcn72.pt')?.bytes)}`,
        `未来天气 TCN ${fmtBytes(artifact('models/forecast_tcn9.pt')?.bytes)}`,
      ],
    },
    {
      step: '5 · 查询库',
      tool: 'SQLite（只读）',
      lines: [
        `城市观测 ${fmtBytes(artifact('data/app/airquality.sqlite')?.bytes)}`,
        `城市预测 ${fmtBytes(artifact('data/app/forecasts.sqlite')?.bytes)}`,
        `站点 ${fmtBytes(artifact('data/app/stations.sqlite')?.bytes)}`,
      ],
    },
    {
      step: '6 · 接口与网页',
      tool: 'FastAPI + Vue + ECharts',
      lines: [
        `站点预测索引 ${fmtInt(indexedPredictions.value)} 行`,
        '实时快照与在线核验库',
        '网页只通过只读接口取数',
      ],
    },
  ]
})

const hdfsOption = computed(() => {
  const rows = [...entries.value].sort((a, b) => (a.bytes ?? 0) - (b.bytes ?? 0))
  const base = baseOption()
  return {
    ...base,
    grid: { top: 8, left: 96, right: 90, bottom: 28 },
    tooltip: {
      ...base.tooltip,
      formatter: items => {
        const item = rows[items[0].dataIndex]
        return `${item.name}/<br/>${fmtBytes(item.bytes)} · ${fmtInt(item.files)} 个文件`
      },
    },
    // 每根柱子末端已标出大小，横轴刻度不再重复显示
    xAxis: valueAxis('', { axisLabel: { show: false } }),
    yAxis: categoryAxis(rows.map(item => `${item.name}/`), {
      axisLine: { show: false },
      axisLabel: { color: ink.secondary, fontSize: 12, fontFamily: 'Consolas, monospace' },
    }),
    series: [{
      type: 'bar',
      data: rows.map(item => item.bytes),
      barMaxWidth: 18,
      itemStyle: { color: palette.green, borderRadius: [0, 4, 4, 0] },
      label: {
        show: true,
        position: 'right',
        color: ink.secondary,
        fontSize: 11,
        formatter: item => fmtBytes(item.value),
      },
    }],
  }
})
</script>

<template>
  <div class="stack">
    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <Notice v-if="!system && !error" kind="loading">正在读取系统证据…</Notice>

    <template v-if="system">
      <Notice v-for="warning in system.warnings" :key="warning.path" kind="warn">
        <code>{{ warning.path }}</code>：{{ warning.message }}
      </Notice>

      <div class="stat-row">
        <StatCard
          label="HDFS 项目数据总量"
          :value="fmtBytes(hdfsTotals.bytes)"
          :icon="HardDrive"
          featured
          :hint="`${entries.length} 个子目录 · 逻辑大小，不含副本`"
        />
        <StatCard
          label="HDFS 文件数"
          :value="fmtInt(hdfsTotals.files)"
          unit="个"
          :icon="FolderTree"
          :hint="inventory ? `盘点于 ${bjFull(inventory.generated_at)}` : '尚未生成盘点'"
        />
        <StatCard
          label="Spark 计算引擎"
          :value="system.versions.spark ? `Spark ${system.versions.spark}` : null"
          word
          :icon="Layers"
          :hint="`运行模式 ${city?.spark_master || '—'}（单机多线程）`"
        />
        <StatCard
          label="GPU 训练与推理"
          :value="system.versions.pytorch ? `PyTorch ${system.versions.pytorch}` : null"
          word
          :icon="Cpu"
          :hint="system.versions.gpu || '报告未记录显卡'"
        />
      </div>

      <PanelCard kicker="数据流水线" title="一条数据从下载到网页经过的六个阶段">
        <ol class="flow">
          <li v-for="stage in stages" :key="stage.step">
            <span class="flow-step">{{ stage.step }}</span>
            <strong>{{ stage.tool }}</strong>
            <span v-for="line in stage.lines" :key="line">{{ line }}</span>
          </li>
        </ol>
        <template #note>
          HDFS 负责存储，Spark 负责清洗、连接和窗口计算，PyTorch 在显卡上训练和推理 TCN；
          这是单机实验环境，不声称已完成多机性能实验。
        </template>
      </PanelCard>

      <PanelCard kicker="HDFS 盘点" title="HDFS 各子目录的真实规模">
        <template #actions>
          <span v-if="inventory" class="tag" :class="inventory.complete ? 'good' : 'warn'">
            {{ inventory.complete ? '六个目录全部盘点成功' : '部分目录盘点失败' }}
          </span>
          <button class="button small" type="button" :disabled="busy" @click="load">
            <RefreshCw :size="14" :class="{ spinning: busy }" />重新读取
          </button>
        </template>
        <Notice v-if="!inventory" kind="warn">
          还没有 HDFS 盘点快照。请在 WSL 中运行 <code>scripts/hdfs_inventory.py</code> 生成。
        </Notice>
        <div v-else class="grid-wide-left">
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>子目录</th>
                  <th>存放内容</th>
                  <th class="num">目录数</th>
                  <th class="num">文件数</th>
                  <th class="num">逻辑大小</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in entries" :key="item.name">
                  <td class="nowrap"><code>{{ item.name }}/</code></td>
                  <td>
                    {{ hdfsPurpose[item.name] || '—' }}
                    <span v-if="item.status !== 'ok'" class="tag danger">
                      {{ item.error || '盘点失败' }}
                    </span>
                  </td>
                  <td class="num">{{ fmtInt(item.directories) }}</td>
                  <td class="num">{{ fmtInt(item.files) }}</td>
                  <td class="num strong">{{ fmtBytes(item.bytes) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <Chart :option="hdfsOption" height="280px" label="HDFS 各子目录逻辑大小" />
        </div>
        <template v-if="inventory" #note>
          根路径 <code>{{ inventory.hdfs_root }}</code>，命令 <code>{{ inventory.command }}</code>，
          盘点时间 {{ bjFull(inventory.generated_at) }}。{{ inventory.note }}
          实时目录会随轮次增长；需要最新数字时重新运行盘点脚本。
        </template>
      </PanelCard>

      <div class="grid-3">
        <PanelCard kicker="第一代" title="城市版数据">
          <dl v-if="city" class="facts">
            <div><dt>时间范围</dt><dd>{{ city.start_date }} 至 {{ city.end_date }}</dd></div>
            <div><dt>城市数</dt><dd>{{ city.cities?.length }} 座</dd></div>
            <div><dt>原始数据</dt><dd>{{ fmtBytes(city.raw_bytes) }}</dd></div>
            <div><dt>城市 × 小时网格</dt><dd>{{ fmtInt(city.panel_rows) }} 行</dd></div>
            <div><dt>有效 PM₂.₅ 小时</dt><dd>{{ fmtInt(city.pm25_valid_hours_all_cities) }}</dd></div>
            <div><dt>北京特征行</dt><dd>{{ fmtInt(city.beijing_feature_rows) }}</dd></div>
          </dl>
          <template #note>来源：<code>{{ system.generations.city?.report }}</code></template>
        </PanelCard>
        <PanelCard kicker="第二代" title="站点版数据">
          <dl v-if="station" class="facts">
            <div><dt>时间范围</dt><dd>{{ station.start }} 至 {{ station.end }}</dd></div>
            <div><dt>历史站点</dt><dd>{{ fmtInt(station.stations) }} 个</dd></div>
            <div><dt>全国原始档案</dt><dd>{{ fmtBytes(station.raw_archive_bytes) }}</dd></div>
            <div><dt>站点 × 小时网格</dt><dd>{{ fmtInt(station.grid_hours) }} 行</dd></div>
            <div><dt>有效 PM₂.₅ 小时</dt><dd>{{ fmtInt(station.valid_pm25) }}</dd></div>
            <div><dt>Spark 特征</dt><dd>{{ station.feature_count }} 列</dd></div>
          </dl>
          <template #note>来源：<code>{{ system.generations.station?.report }}</code></template>
        </PanelCard>
        <PanelCard kicker="第三代" title="未来天气模型数据">
          <dl v-if="forecast" class="facts">
            <div><dt>小时网格长度</dt><dd>{{ fmtInt(forecast.hours) }} 小时</dd></div>
            <div><dt>城市数</dt><dd>{{ forecast.cities?.length }} 座</dd></div>
            <div><dt>历史输入通道</dt><dd>{{ forecast.sequence_columns?.length }} 个</dd></div>
            <div><dt>未来天气通道</dt><dd>{{ forecast.weather_columns?.length }} 个</dd></div>
            <div>
              <dt>天气模型</dt>
              <dd>{{ forecast.weather_model }} · 提前 {{ forecast.weather_lead_hours }} h</dd>
            </div>
            <div><dt>有效天气小时</dt><dd>{{ fmtInt(forecast.weather_valid_hours) }}</dd></div>
          </dl>
          <template #note>来源：<code>{{ system.generations.forecast?.report }}</code></template>
        </PanelCard>
      </div>

      <div class="grid-2">
        <PanelCard
          kicker="组件版本"
          title="版本号与出处"
          note="版本号只引用已有报告中的记录；报告里没有的显示为“报告未记录”，不在页面上补写。"
        >
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>组件</th>
                  <th>版本</th>
                  <th>出处（报告 → 字段）</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in versionRows" :key="row.key">
                  <td>{{ row.name }}</td>
                  <td :class="row.value ? 'strong' : 'muted'">{{ row.value || '报告未记录' }}</td>
                  <td>
                    <code v-if="row.source">{{ row.source }}</code>
                    <span v-else class="muted">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </PanelCard>

        <PanelCard
          kicker="时间划分"
          title="三代系统各自的训练与测试切分"
          note="都按时间先后划分，从不打乱；推荐模型只看验证（选择）期，测试期只做最后评价。"
        >
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>代次</th>
                  <th>训练</th>
                  <th>验证 / 选择</th>
                  <th>测试</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>城市版</td>
                  <td>2015—2023</td>
                  <td>2024</td>
                  <td>2025</td>
                </tr>
                <tr v-if="station">
                  <td>站点版</td>
                  <td>至 {{ station.splits?.train_end }}</td>
                  <td>{{ station.splits?.validation }}</td>
                  <td>{{ station.splits?.test }}</td>
                </tr>
                <tr v-if="forecast">
                  <td>未来天气版</td>
                  <td>{{ forecast.splits?.train }}</td>
                  <td>
                    {{ forecast.splits?.selection }}<br />
                    <span class="muted">校准 {{ forecast.splits?.calibration }}</span>
                  </td>
                  <td>{{ forecast.splits?.test }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </PanelCard>
      </div>

      <PanelCard kicker="产物清单" title="各流水线阶段留下的文件">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>流水线</th>
                <th>用途</th>
                <th>路径</th>
                <th class="num">大小</th>
                <th>更新时间</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="group in artifactGroups" :key="group.pipeline">
                <tr v-for="(item, index) in group.items" :key="item.path">
                  <td>
                    <strong v-if="index === 0">
                      {{ pipelineNames[group.pipeline] || group.pipeline }}
                    </strong>
                  </td>
                  <td>{{ item.stage }}</td>
                  <td><code>{{ item.path }}</code></td>
                  <td class="num">{{ fmtBytes(item.bytes) }}</td>
                  <td class="nowrap">{{ bjFull(item.modified_at) }}</td>
                  <td>
                    <span class="tag" :class="item.exists ? 'good' : 'danger'">
                      {{ item.exists ? '存在' : '缺失' }}
                    </span>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <template #note>
          大小与时间是本次打开页面时读取的文件元数据（{{ bjFull(system.checked_at) }}）。{{ system.note }}
        </template>
      </PanelCard>

      <PanelCard kicker="与课程教材的对照" title="教材案例用到的工具，本项目用什么代替">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>教材案例</th>
                <th>本项目</th>
                <th>选择理由</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in textbook" :key="row[0]">
                <td>{{ row[0] }}</td>
                <td class="strong">{{ row[1] }}</td>
                <td>{{ row[2] }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <template #note>借鉴教材的数据流水线思路，具体工具按数据格式、本地运行方式和模型需求选择。</template>
      </PanelCard>

      <div class="method-note">
        <Info :size="16" aria-hidden="true" />
        <p>
          <Database :size="13" aria-hidden="true" /> 页面数字来自 <code>/api/system</code>：
          HDFS 数字是盘点脚本生成时的快照，不会每次打开网页都重新统计；
          在 WSL 中运行 <code>scripts/hdfs_inventory.py</code> 可以更新。
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 六个阶段从左到右排列，窄屏时改为上下排列 */
.flow {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.flow li {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: 14px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  font-size: 12px;
  color: var(--ink-2);
}

.flow li:not(:last-child)::after {
  content: "→";
  position: absolute;
  top: 50%;
  right: -13px;
  transform: translateY(-50%);
  color: var(--ink-3);
}

.flow-step {
  font-weight: 650;
  color: var(--brand);
}

.flow strong {
  margin-bottom: 4px;
  font-size: 14px;
  color: var(--ink);
}

.facts {
  display: grid;
  gap: 0;
  margin: 0;
}

.facts div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}

.facts div:last-child {
  border-bottom: 0;
}

.facts dt {
  color: var(--ink-3);
}

.facts dd {
  margin: 0;
  font-weight: 600;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.method-note svg {
  vertical-align: -2px;
}

@media (max-width: 1180px) {
  .flow {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .flow li::after {
    display: none;
  }
}
</style>
