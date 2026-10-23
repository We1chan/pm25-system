<script setup>
/*
 * 数据质量页（第一代城市数据，附第二代站点数据摘要）。
 * 数据：/api/quality（reports/data_summary.json 与逐年逐城质量表）、/api/stations/meta（站点数据摘要）。
 * 页面上的规模数字全部读自报告，不在前端写死。缺失保留为空，不当作零浓度。
 */
import { computed, onMounted, ref } from 'vue'
import {
  ArrowUpRight,
  CircleCheck,
  CloudSun,
  Database,
  FileExclamationPoint,
  HardDrive,
  Rows3,
} from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import StatCard from '../components/StatCard.vue'
import YearBar from '../components/YearBar.vue'
import { api } from '../lib/api'
import { fmt, fmtBytes, fmtInt, fmtPercent } from '../lib/format'
import { cityIds, cityNames } from '../lib/labels'
import { historyYear, loadHistoryMeta } from '../lib/state'
import { baseOption, categoryAxis, greenRamp, ink } from '../lib/chart'

const meta = ref(null)
const data = ref(null)
const stationMeta = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    const [history, quality] = await Promise.all([loadHistoryMeta(), api('quality')])
    meta.value = history
    data.value = quality
  } catch (reason) {
    error.value = reason.message
  }
  // 站点摘要是补充信息，读取失败不影响本页主体
  stationMeta.value = await api('stations/meta').catch(() => null)
})

const summary = computed(() => data.value?.summary || {})
const verification = computed(() => data.value?.verification || {})

const validRatio = computed(() => {
  if (!summary.value.panel_rows) {
    return null
  }
  return summary.value.pm25_valid_hours_all_cities / summary.value.panel_rows
})

const rawFileHint = computed(() => {
  const download = summary.value.download_summary || {}
  const air = download.air?.ok || 0
  const weather = download.weather?.ok || 0
  return `${fmtInt(air)} 份空气质量 + ${fmtInt(weather)} 份气象，共 ${fmtInt(air + weather)} 份`
})

const yearTitle = computed(() => {
  return historyYear.value === 'all' ? '全部年份' : `${historyYear.value} 年`
})

const rows = computed(() => {
  const all = data.value?.rows || []
  if (historyYear.value === 'all') {
    return all
  }
  return all.filter(row => row.year === Number(historyYear.value))
})

const stationSummary = computed(() => {
  return stationMeta.value?.summary?.status === 'complete' ? stationMeta.value.summary : null
})

function formatDay(day) {
  return `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6, 8)}`
}

const coverageOption = computed(() => {
  const years = meta.value?.years || []
  const cells = (data.value?.rows || []).map(row => {
    const value = Number(((1 - row.pm25_missing_ratio) * 100).toFixed(2))
    return {
      value: [years.indexOf(row.year), cityIds.indexOf(row.city_id), value],
      // 深色格子用白字
      label: { color: value >= 96 ? '#fff' : ink.primary },
    }
  })
  return {
    textStyle: baseOption().textStyle,
    tooltip: {
      confine: true,
      formatter: item => {
        const [x, y, value] = item.value
        return `${cityNames[cityIds[y]]} · ${years[x]} 年<br/>有效观测覆盖率 <b>${fmt(value, 2)}%</b>`
      },
    },
    grid: { top: 6, left: 56, right: 12, bottom: 28 },
    xAxis: categoryAxis(years, { axisLine: { show: false } }),
    yAxis: categoryAxis(cityIds.map(id => cityNames[id]), {
      axisLine: { show: false },
      axisLabel: { color: ink.secondary },
    }),
    visualMap: { show: false, min: 85, max: 100, inRange: { color: greenRamp.slice(1) } },
    series: [{
      type: 'heatmap',
      data: cells,
      label: { show: true, fontSize: 11, formatter: item => fmt(item.value[2], 1) },
      itemStyle: { borderColor: '#fff', borderWidth: 3, borderRadius: 4 },
    }],
  }
})
</script>

<template>
  <div class="stack">
    <YearBar :years="meta?.years || []" exportable />

    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <Notice v-if="!data && !error" kind="loading">正在读取数据质量报告…</Notice>

    <template v-if="data">
      <div class="stat-row">
        <StatCard
          label="六城 × 小时完整网格"
          :value="fmtInt(summary.panel_rows)"
          unit="行"
          :icon="Rows3"
          featured
          hint="每个城市每个小时一行；缺测保留为空"
        />
        <StatCard
          label="有效 PM₂.₅ 小时观测"
          :value="fmtInt(summary.pm25_valid_hours_all_cities)"
          :icon="Database"
          :hint="`占网格的 ${fmtPercent(validRatio, 2)}`"
        />
        <StatCard
          label="原始数据总量"
          :value="fmtBytes(summary.raw_bytes)"
          :icon="HardDrive"
          :hint="rawFileHint"
        />
        <StatCard
          label="来源缺失的整日文件"
          :value="fmtInt(summary.source_missing_dates?.length)"
          unit="天"
          :icon="FileExclamationPoint"
          hint="已向原站复查并记录，保留为空"
        />
      </div>

      <PanelCard
        kicker="观测覆盖"
        title="十一年观测的完整程度（有效 PM₂.₅ 小时占比 %）"
        note="缺失包括整日源文件缺失、部分小时缺失和城市观测为空；颜色越深越完整。"
      >
        <Chart :option="coverageOption" height="270px" label="六城十一年 PM2.5 有效观测覆盖率" />
      </PanelCard>

      <div class="grid-3">
        <section class="panel source">
          <Database :size="22" aria-hidden="true" />
          <h2>空气质量观测</h2>
          <p>
            中国环境监测总站发布的城市小时数据，由 quotsoft 公开存档。逐文件保存来源和 SHA-256，
            并与原站跨年份抽样核对。
          </p>
          <a href="https://quotsoft.net/air/" target="_blank" rel="noreferrer">
            查看数据源 <ArrowUpRight :size="13" />
          </a>
        </section>
        <section class="panel source">
          <CloudSun :size="22" aria-hidden="true" />
          <h2>气象再分析资料</h2>
          <p>
            Open-Meteo 提供的 ERA5 小时数据，在各城市代表坐标提取：气温、湿度、气压、风速、风向、降水。
          </p>
          <a
            href="https://open-meteo.com/en/docs/historical-weather-api"
            target="_blank"
            rel="noreferrer"
          >
            查看气象说明 <ArrowUpRight :size="13" />
          </a>
        </section>
        <section class="panel source">
          <CircleCheck :size="22" aria-hidden="true" />
          <h2>清洗核验</h2>
          <ul class="checks">
            <li>数据处理单元测试 {{ fmtInt(verification.unit_tests_passed) }} 项通过</li>
            <li>原始值与未来标签抽查 {{ fmtInt(verification.source_cell_and_target_checks) }} 项通过</li>
            <li>
              Parquet 导出后重新读取：
              {{ verification.local_parquet_readback === 'passed' ? '通过' : '未通过' }}
            </li>
            <li>
              网格 {{ fmtInt(verification.panel?.rows) }} 行，
              特征 {{ fmtInt(verification.features?.rows) }} 行
            </li>
          </ul>
        </section>
      </div>

      <PanelCard kicker="质量报告" :title="`逐年逐城覆盖明细 · ${yearTitle}`">
        <template #actions>
          <span class="tag">{{ rows.length }} 条记录</span>
        </template>
        <div class="table-wrap tall">
          <table>
            <thead>
              <tr>
                <th>年份</th>
                <th>城市</th>
                <th class="num">应有小时</th>
                <th class="num">有效观测</th>
                <th class="num">缺失比例</th>
                <th class="num">PM₂.₅ 年均</th>
                <th class="num">最小 / 最大</th>
                <th class="num">非法值 / 冲突值</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="`${row.year}-${row.city_id}`">
                <td>{{ row.year }}</td>
                <td>{{ row.city_name }}</td>
                <td class="num">{{ fmtInt(row.expected_hours) }}</td>
                <td class="num">{{ fmtInt(row.pm25_valid_hours) }}</td>
                <td class="num">{{ fmtPercent(row.pm25_missing_ratio, 2) }}</td>
                <td class="num strong">{{ fmt(row.pm25_mean) }}</td>
                <td class="num">{{ fmt(row.pm25_min, 0) }} / {{ fmt(row.pm25_max, 0) }}</td>
                <td class="num">
                  {{ fmtInt(row.invalid_air_values) }} / {{ fmtInt(row.conflicting_air_values) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <template #note>浓度单位 μg/m³。非法值（如负数）和同一小时的冲突值会被置空并计数。</template>
      </PanelCard>

      <PanelCard kicker="来源缺失" title="原始来源缺少的日期">
        <div class="date-tags">
          <span v-for="day in summary.source_missing_dates" :key="day" class="tag">
            {{ formatDay(day) }}
          </span>
        </div>
        <template #note>这些日期原站和存档都没有文件，分析和建模时保留为空，不做插值。</template>
      </PanelCard>

      <PanelCard
        v-if="stationSummary"
        kicker="第二代站点数据"
        :title="`${stationSummary.start} 至 ${stationSummary.end} 的站点数据`"
      >
        <template #actions>
          <a href="#stations" class="button small">查看站点与 GPU <ArrowUpRight :size="13" /></a>
        </template>
        <p class="panel-text">
          {{ fmtInt(stationSummary.stations) }} 个历史站点 ·
          {{ fmtInt(stationSummary.valid_pm25) }} 条有效站点小时 PM₂.₅ ·
          {{ fmtInt(stationSummary.grid_hours) }} 行完整小时网格。
        </p>
        <p class="panel-text">
          全国逐站小时原始档案 {{ fmtBytes(stationSummary.raw_archive_bytes) }}，共
          {{ fmtInt(stationSummary.source_file_count) }} 份文件；原始日期覆盖
          {{ fmtInt(stationSummary.source_days) }} / {{ fmtInt(stationSummary.expected_days) }} 天。
        </p>
        <template #note>两代数据保留各自的统计口径，不直接相加。</template>
      </PanelCard>
    </template>
  </div>
</template>

<style scoped>
.source {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.source svg {
  color: var(--brand);
}

.source h2 {
  font-size: 16px;
}

.source p,
.checks {
  font-size: 13px;
  color: var(--ink-2);
}

.source a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: auto;
  font-size: 13px;
}

.checks {
  display: grid;
  gap: 4px;
  margin: 0;
  padding-left: 18px;
}

.date-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
