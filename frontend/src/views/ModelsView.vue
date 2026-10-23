<script setup>
/*
 * 模型评估页（第一代，北京城市均值，Spark ML）。
 * 数据：/api/models（models/registry.json 的模型登记与评估结果，不触发训练）。
 * 规则：按时间划分 2015—2023 训练、2024 验证、2025 测试；
 *       推荐模型只按 2024 验证集 RMSE 选，即使别的模型在测试集更好也不据此更换。
 */
import { computed, onMounted, ref } from 'vue'
import { Info } from '@lucide/vue'
import Chart from '../components/Chart.vue'
import Notice from '../components/Notice.vue'
import PanelCard from '../components/PanelCard.vue'
import Segmented from '../components/Segmented.vue'
import StatCard from '../components/StatCard.vue'
import { api } from '../lib/api'
import { fmt, fmtInt } from '../lib/format'
import { cityModelNames, featureLabel } from '../lib/labels'
import {
  barSeries,
  baseOption,
  categoryAxis,
  categoryTooltip,
  ink,
  legend,
  lineSeries,
  modelColors,
  palette,
  valueAxis,
} from '../lib/chart'

const data = ref(null)
const error = ref('')
const split = ref('test')
const horizon = ref(6)

const horizons = [1, 2, 3, 4, 5, 6]
const modelIds = ['rf', 'gbt', 'persistence']
const splitOptions = [
  { value: 'test', label: '2025 独立测试' },
  { value: 'validation', label: '2024 验证' },
]

onMounted(async () => {
  try {
    data.value = await api('models')
  } catch (reason) {
    error.value = reason.message
  }
})

const registry = computed(() => data.value?.registry || null)
const runs = computed(() => Object.values(registry.value?.runs || {}))

// 区域特征（完整输入）下各模型在当前期间的指标
function regional(modelId, h) {
  const run = runs.value.find(item => {
    return item.variant === 'regional' && item.model === modelId && item.horizon === h
  })
  const metrics = run?.metrics.find(item => item.split === split.value)
  return metrics ? { ...run, ...metrics } : null
}

const rf6 = computed(() => regional('rf', 6))
const baseline6 = computed(() => regional('persistence', 6))

const improvement = computed(() => {
  if (!rf6.value || !baseline6.value) {
    return null
  }
  return (1 - rf6.value.rmse / baseline6.value.rmse) * 100
})

// 推荐模型（按验证集）：把六个时长的推荐结果合并成一句话
const recommendedText = computed(() => {
  const mapping = registry.value?.recommended_by_horizon || {}
  const names = [...new Set(Object.values(mapping))]
  if (!names.length) {
    return null
  }
  return names.map(id => cityModelNames[id] || id).join('、')
})

const tableRows = computed(() => {
  const rows = []
  for (const h of horizons) {
    for (const id of modelIds) {
      const row = regional(id, h)
      if (row) {
        rows.push(row)
      }
    }
  }
  return rows
})

// ---------- 图表 ----------

const errorOption = computed(() => {
  const base = baseOption()
  return {
    ...base,
    legend: legend(modelIds.map(id => cityModelNames[id])),
    tooltip: { ...base.tooltip, formatter: categoryTooltip({ digits: 2 }) },
    xAxis: categoryAxis(horizons.map(h => `+${h} h`)),
    yAxis: valueAxis('RMSE μg/m³'),
    series: modelIds.map(id => lineSeries({
      name: cityModelNames[id],
      data: horizons.map(h => regional(id, h)?.rmse ?? null),
      color: modelColors[id],
      width: id === 'rf' ? 2.5 : 2,
      dashed: id === 'persistence',
      points: true,
    })),
  }
})

// 特征消融：固定随机森林，只改变输入特征组
const ablationGroups = [
  { variant: 'beijing', label: '只用北京污染历史', color: '#b7d3f6' },
  { variant: 'weather', label: '+ 北京天气', color: '#6da7ec' },
  { variant: 'regional', label: '+ 周边城市污染与天气', color: palette.blue },
]

const ablationOption = computed(() => {
  const values = ablationGroups.map(group => {
    const run = runs.value.find(item => {
      return item.variant === group.variant && item.model === 'rf' && item.horizon === horizon.value
    })
    return run?.metrics.find(item => item.split === split.value)?.rmse ?? null
  })
  const base = baseOption()
  return {
    ...base,
    grid: { ...base.grid, top: 34 },
    tooltip: { ...base.tooltip, formatter: categoryTooltip({ digits: 2 }) },
    xAxis: categoryAxis(ablationGroups.map(group => group.label), {
      axisLabel: { color: ink.secondary, fontSize: 12, interval: 0 },
    }),
    yAxis: valueAxis(`+${horizon.value} h RMSE μg/m³`),
    series: [barSeries({
      name: `+${horizon.value} h RMSE`,
      data: values.map((value, index) => ({
        value,
        itemStyle: { color: ablationGroups[index].color },
      })),
      color: palette.blue,
      width: 48,
      labels: true,
    })],
  }
})

const importance = computed(() => {
  const run = runs.value.find(item => {
    return item.variant === 'regional' && item.model === 'rf' && item.horizon === horizon.value
  })
  return (run?.feature_importance || []).slice(0, 12).reverse()
})

const importanceOption = computed(() => {
  const base = baseOption()
  return {
    ...base,
    grid: { top: 8, left: 190, right: 56, bottom: 24 },
    tooltip: {
      ...base.tooltip,
      formatter: items => `${items[0].name}<br/>重要性 <b>${fmt(items[0].value * 100, 2)}%</b>`,
    },
    xAxis: valueAxis('', {
      axisLabel: { color: ink.muted, formatter: value => `${Math.round(value * 100)}%` },
    }),
    yAxis: categoryAxis(importance.value.map(item => featureLabel(item.feature)), {
      axisLine: { show: false },
      axisLabel: { color: ink.secondary, fontSize: 12, width: 180, overflow: 'truncate' },
    }),
    series: [{
      type: 'bar',
      data: importance.value.map(item => item.importance),
      barMaxWidth: 14,
      itemStyle: { color: palette.blue, borderRadius: [0, 4, 4, 0] },
      label: {
        show: true,
        position: 'right',
        color: ink.secondary,
        fontSize: 11,
        formatter: item => `${fmt(item.value * 100, 1)}%`,
      },
    }],
  }
})
</script>

<template>
  <div class="stack">
    <Notice v-if="error" kind="error">{{ error }}</Notice>
    <Notice v-if="!data && !error" kind="loading">正在读取实验结果…</Notice>

    <template v-if="registry">
      <ol class="timeline" aria-label="按时间划分的数据集">
        <li>
          <span>训练集</span>
          <strong>{{ registry.train_period }}</strong>
          <small>拟合模型与缺失值处理器</small>
        </li>
        <li>
          <span>验证集</span>
          <strong>{{ registry.validation_period }}</strong>
          <small>为每个时长选择推荐模型</small>
        </li>
        <li class="active">
          <span>测试集</span>
          <strong>{{ registry.test_period }}</strong>
          <small>只用于最后的独立评价</small>
        </li>
        <li class="engine">
          <span>训练引擎</span>
          <strong>{{ registry.engine }}</strong>
          <small>残差回归 · 每个时长单独训练</small>
        </li>
      </ol>

      <div class="controls">
        <Segmented v-model="split" label="评估期间" :options="splitOptions" />
        <label class="horizon">
          消融与特征重要性的预测时长
          <select v-model.number="horizon" class="select">
            <option :value="1">未来 1 小时</option>
            <option :value="3">未来 3 小时</option>
            <option :value="6">未来 6 小时</option>
          </select>
        </label>
        <span class="muted">指标越低越好；测试集不参与选择模型</span>
      </div>

      <div class="stat-row three">
        <StatCard
          label="随机森林 · 未来 6 小时 RMSE"
          :value="fmt(rf6?.rmse, 2)"
          unit="μg/m³"
          featured
          :hint="`${fmtInt(rf6?.n)} 个与基线相同的评估样本`"
        />
        <StatCard
          label="相比持续性基线"
          :value="fmt(improvement)"
          unit="% RMSE 降低"
          :hint="`持续性基线 RMSE ${fmt(baseline6?.rmse, 2)} μg/m³`"
        />
        <StatCard
          label="推荐模型（按 2024 验证集）"
          :value="recommendedText"
          word
          hint="六个预测时长分别比较后得出"
        />
      </div>

      <div class="grid-2">
        <PanelCard
          kicker="模型比较"
          title="预测越远，误差如何变化"
          note="区域特征（完整输入）；同一时长内三种方法使用相同的评估样本。"
        >
          <Chart :option="errorOption" height="300px" label="三种方法各预测时长 RMSE" />
        </PanelCard>
        <PanelCard
          kicker="特征消融"
          title="加入天气和周边城市信息有没有帮助"
          note="固定随机森林算法和参数，只改变输入特征组，在相同样本上比较。"
        >
          <Chart :option="ablationOption" height="300px" label="三组输入特征的随机森林 RMSE" />
        </PanelCard>
      </div>

      <div class="grid-2">
        <PanelCard
          kicker="特征重要性"
          :title="`随机森林最依赖哪些信息（+${horizon} h）`"
          note="树模型的特征重要性反映分裂时的贡献，不代表因果影响。"
        >
          <Chart :option="importanceOption" height="380px" label="随机森林前十二项特征重要性" />
        </PanelCard>
        <PanelCard kicker="评估明细" title="各模型 · 各时长">
          <div class="table-wrap tall">
            <table>
              <thead>
                <tr>
                  <th>时长</th>
                  <th>模型</th>
                  <th class="num">MAE</th>
                  <th class="num">RMSE</th>
                  <th class="num">R²</th>
                  <th class="num">样本</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in tableRows" :key="`${row.model}-${row.horizon}`">
                  <td>+{{ row.horizon }} h</td>
                  <td>
                    <i class="swatch" :style="{ background: modelColors[row.model] }"></i>
                    {{ cityModelNames[row.model] }}
                  </td>
                  <td class="num">{{ fmt(row.mae, 2) }}</td>
                  <td class="num strong">{{ fmt(row.rmse, 2) }}</td>
                  <td class="num">{{ fmt(row.r2, 3) }}</td>
                  <td class="num">{{ fmtInt(row.n) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </PanelCard>
      </div>

      <div class="method-note">
        <Info :size="16" aria-hidden="true" />
        <p>
          每个时长单独训练。训练时排除标签跨出所属年份的样本；缺失特征用训练集中位数填补，验证和测试沿用同一处理器。
          推荐模型只依据 2024 年验证集 RMSE 选取。气象为 ERA5 再分析资料，测试成绩不构成在线精度证明。
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.timeline {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(0, 1.2fr);
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 16px;
  border-radius: var(--radius);
  background: var(--surface);
  border: 1px solid var(--border);
}

.timeline li.active {
  background: var(--brand-soft);
  border-color: var(--brand-line);
}

.timeline li.engine {
  background: var(--surface-sunken);
  border-style: dashed;
}

.timeline span {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-3);
}

.timeline strong {
  font-size: 20px;
}

.timeline small {
  font-size: 12px;
  color: var(--ink-3);
}

.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 20px;
  font-size: 13px;
}

.horizon {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--ink-2);
}

td .swatch {
  margin-right: 6px;
  vertical-align: -1px;
}

@media (max-width: 1180px) {
  .timeline {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
