<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowRight } from '@lucide/vue'
import { api } from '../lib/api'
import { bjFull, fmt, fmtInt, fmtPercent, isNumber } from '../lib/format'
import { verificationHref } from '../lib/liveLinks'

const release = ref()
const evaluation = ref()
const report = ref()

async function readEvidence(path, target) {
  try {
    target.value = await api(path)
  } catch {
    target.value = null
  }
}

onMounted(() => {
  readEvidence('live/meta', release)
  readEvidence('live/evaluation', evaluation)
  readEvidence('live/model', report)
})

const hasRelease = computed(() => release.value?.ready && Boolean(release.value.issued_at))
const hasStationCounts = computed(() => isNumber(release.value?.forecast_stations)
  && isNumber(release.value?.beijing_stations) && release.value.beijing_stations > 0)

const example = computed(() => {
  const row = evaluation.value?.recent_case
  if (row?.status !== 'verified' || !row.station_id || !row.cycle_id || !row.target
    || !isNumber(row.prediction) || !isNumber(row.actual)) return null
  const station = release.value?.stations?.find(item => item.station_id === row.station_id)
  return {
    ...row,
    stationName: station?.name || row.station_id,
    absoluteError: Math.abs(row.prediction - row.actual),
    href: verificationHref(row.cycle_id, row.station_id, row.target, '#achievements'),
  }
})

const experiment = computed(() => {
  const runs = report.value?.runs
  if (!report.value?.ready) return null
  const future = runs?.future_weather?.test?.by_horizon
  const history = runs?.history_only?.test?.by_horizon
  const forecast6 = future?.find(row => row.horizon === 6)
  const history6 = history?.find(row => row.horizon === 6)
  const groups = [
    { label: '加入未来天气', rmse: forecast6?.rmse, featured: true },
    { label: '仅用历史浓度和天气', rmse: history6?.rmse },
    { label: '沿用起点实测', rmse: forecast6?.baseline_rmse },
  ]
  if (!groups.every(row => isNumber(row.rmse) && Number(row.rmse) >= 0)) return null
  return {
    groups,
    scale: Math.max(5, Math.ceil(Math.max(...groups.map(row => row.rmse)) / 5) * 5),
    gain: history6.rmse > 0 ? 1 - forecast6.rmse / history6.rmse : null,
    // 报告生成器用同一批测试样本评估两组模型。
    sampleCount: Number(forecast6.n) > 0 && forecast6.n === history6.n ? forecast6.n : null,
    forecast1: future.find(row => row.horizon === 1),
  }
})

const sameWeights = computed(() => hasRelease.value && Boolean(report.value?.checkpoint_sha256)
  && report.value.checkpoint_sha256 === release.value.checkpoint_sha256)
const online = computed(() => {
  const summary = evaluation.value?.summary
  if (!(summary?.n > 0)) return null
  const days = evaluation.value.by_day?.filter(row => row.n > 0).length ?? null
  const shortCoverage = evaluation.value.uncertainty?.by_horizon?.some(row => row.n_days < 7)
  return {
    count: summary.n,
    mae: summary.mae,
    days,
    shortCoverage,
  }
})
const onlinePeriod = computed(() => {
  const range = evaluation.value?.filters
  return range?.start && range?.end ? range.start + ' 至 ' + range.end : ''
})
</script>

<template>
  <div class="achievements">
    <header class="achievement-lead">
      <div class="lead-copy">
        <h1>北京 PM₂.₅<br class="title-break" /> 预测成果</h1>
        <p class="lead-text">系统发布北京监测站未来六个整点的 PM₂.₅ 预测，实测到达后自动核验。</p>
        <a class="button primary live-action" href="#live">
          查看实时预测 <ArrowRight :size="16" aria-hidden="true" />
        </a>

        <dl v-if="hasRelease" class="release-facts" aria-label="最近一轮发布">
          <div>
            <dt>最近发布时间</dt>
            <dd>{{ bjFull(release.issued_at) }}</dd>
          </div>
          <div v-if="hasStationCounts">
            <dt>本轮覆盖的北京站点</dt>
            <dd>{{ fmtInt(release.forecast_stations) }} / {{ fmtInt(release.beijing_stations) }} 个</dd>
          </div>
        </dl>
        <p v-else class="release-state" role="status">
          {{ release === undefined ? '正在读取最近一轮发布…' : release ? '暂无可展示的发布轮次。' : '暂时无法读取最近一轮发布。' }}
        </p>
      </div>

      <section class="proof-sheet" aria-labelledby="achievement-case">
        <h2 id="achievement-case">一条已核验的预测</h2>
        <template v-if="example">
          <p class="proof-station">{{ example.stationName }}</p>
          <div class="proof-times">
            <span v-if="example.issued_at">发布于 {{ bjFull(example.issued_at) }}</span>
            <span>预测目标 {{ bjFull(example.target) }}</span>
          </div>
          <dl class="proof-values" aria-label="预测和实测的 PM₂.₅ 浓度，单位为微克每立方米">
            <div><dt>预测</dt><dd>{{ fmt(example.prediction) }}</dd></div>
            <div><dt>实测</dt><dd>{{ fmt(example.actual) }}</dd></div>
            <div><dt>相差</dt><dd>{{ fmt(example.absoluteError) }}</dd></div>
          </dl>
          <div class="proof-footer">
            <span>单位 μg/m³</span>
            <a :href="example.href">查看这条记录 <ArrowRight :size="15" aria-hidden="true" /></a>
          </div>
        </template>
        <p v-else class="proof-empty" role="status">
          {{ evaluation === undefined ? '正在查找一条已核验记录…'
            : evaluation ? '实测到达并配对后，这里会展示一条可复查的预测。' : '暂时无法读取核验记录。' }}
        </p>
      </section>
    </header>

    <section class="experiment-section" aria-labelledby="achievement-experiment">
      <div class="experiment-copy">
        <h2 id="achievement-experiment">加入未来天气，预测更准吗？</h2>
        <p class="section-context">2025 年独立测试 · 北京监测站</p>

        <template v-if="experiment">
          <p v-if="experiment.gain !== null" class="weather-gain">
            <template v-if="experiment.gain === 0"><strong>误差持平</strong></template>
            <template v-else>
              <span>提前 6 小时的误差{{ experiment.gain > 0 ? '下降' : '上升' }}</span>
              <strong>{{ fmtPercent(Math.abs(experiment.gain)) }}</strong>
            </template>
          </p>
          <p class="section-text">
            以仅用历史浓度和天气的模型为参照，检验额外加入未来天气预报的效果。
            <template v-if="experiment.sampleCount">对比使用相同的 {{ fmtInt(experiment.sampleCount) }} 条站点小时样本。</template>
          </p>
          <p v-if="sameWeights" class="model-context">测试报告与最近一轮实时预测使用同一份权重。</p>
          <p v-else-if="report.checkpoint_sha256" class="model-context">
            历史报告模型版本 {{ report.checkpoint_sha256.slice(0, 8) }}<template v-if="hasRelease && release.checkpoint_sha256">，最近发布版本 {{ release.checkpoint_sha256.slice(0, 8) }}</template>。
          </p>
        </template>
        <p v-else class="section-text" role="status">
          {{ report === undefined ? '正在读取历史测试报告…' : report ? '暂时没有可展示的六小时对照结果。' : '暂时无法读取历史测试报告。' }}
        </p>
        <a class="evidence-link" href="#model-test">查看历史对照实验 <ArrowRight :size="16" aria-hidden="true" /></a>
      </div>

      <figure v-if="experiment" class="error-figure">
        <figcaption>
          <strong>提前 6 小时的预测误差</strong>
          <span>均方根误差 RMSE（μg/m³），越低越好</span>
        </figcaption>
        <ul class="error-bars">
          <li v-for="row in experiment.groups" :key="row.label" :class="{ featured: row.featured }">
            <span>{{ row.label }}</span>
            <strong>{{ fmt(row.rmse, 2) }}</strong>
            <div class="bar-track" aria-hidden="true">
              <span :style="{ width: row.rmse / experiment.scale * 100 + '%' }"></span>
            </div>
          </li>
        </ul>
        <div class="bar-scale" aria-hidden="true"><span>0</span><span>{{ experiment.scale }}</span></div>
        <p v-if="isNumber(experiment.forecast1?.rmse) && isNumber(experiment.forecast1?.baseline_rmse)
          && experiment.forecast1.rmse > experiment.forecast1.baseline_rmse" class="figure-note">
          提前 1 小时，沿用起点实测的误差为 {{ fmt(experiment.forecast1.baseline_rmse, 2) }}，加入未来天气的模型为 {{ fmt(experiment.forecast1.rmse, 2) }}。
        </p>
      </figure>
    </section>

    <section class="online-section" aria-labelledby="achievement-online">
      <header class="online-heading">
        <div>
          <h2 id="achievement-online">上线后的预测与实测</h2>
          <p v-if="onlinePeriod" class="section-context">{{ onlinePeriod }} · 北京监测站</p>
        </div>
        <a class="evidence-link" href="#online">查看在线核验明细 <ArrowRight :size="16" aria-hidden="true" /></a>
      </header>

      <template v-if="online">
        <dl class="online-values">
          <div>
            <dt>已配对的预测与实测</dt>
            <dd>{{ fmtInt(online.count) }} <span>条</span></dd>
          </div>
          <div>
            <dt>预测与实测平均相差</dt>
            <dd>{{ fmt(online.mae, 2) }} <span v-if="isNumber(online.mae)">μg/m³</span></dd>
          </div>
          <div>
            <dt>有核验记录的日期</dt>
            <dd>{{ fmtInt(online.days) }} <span v-if="online.days !== null">天</span></dd>
          </div>
        </dl>
        <p class="online-note">
          每条记录是一对单站预测和实测，误差按已配对的样本计算。
          <template v-if="online.shortCoverage">
            部分预测时长的核验覆盖不足 7 天，表现还需要更多数据确认。
          </template>
        </p>
      </template>
      <p v-else class="online-note" role="status">
        {{ evaluation === undefined ? '正在读取在线核验统计…'
          : evaluation ? '当前范围内暂无已配对实测。' : '暂时无法读取在线核验统计。' }}
      </p>
    </section>
  </div>
</template>

<style scoped>
.achievements {
  --report-ink: #172a22;
  --report-muted: #4a5d51;
  --report-line: #dbe3db;
  --proof-ink: #f3fbf5;
  --proof-muted: #c5dfd2;
  --proof-line: #638779;
  display: grid;
  gap: clamp(30px, 4vw, 52px);
  color: var(--report-ink);
}

.achievements h2 {
  font-size: clamp(1.42rem, 2.4vw, 2.05rem);
  line-height: 1.32;
  letter-spacing: -0.025em;
}

.achievement-lead, .experiment-section {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: clamp(24px, 5vw, 68px);
  align-items: start;
}

.achievement-lead {
  padding-top: clamp(4px, 0.8vw, 12px);
}

.lead-copy {
  min-width: 0;
  padding-block: clamp(5px, 1vw, 14px);
}

.lead-copy h1 {
  font-size: clamp(2.5rem, 4.2vw, 4rem);
  line-height: 1.12;
  font-weight: 700;
  letter-spacing: -0.035em;
}

.lead-text {
  max-width: 36ch;
  margin-top: 18px;
  color: var(--report-muted);
  font-size: clamp(1.04rem, 1.3vw, 1.24rem);
  line-height: 1.75;
}

.live-action {
  min-height: 42px;
  margin-top: 20px;
  gap: 10px;
}

.release-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 22px;
  margin: 24px 0 0;
  padding-top: 14px;
  border-top: 1px solid var(--report-line);
}

.release-facts dt, .release-state {
  color: var(--report-muted);
  font-size: 0.93rem;
}

.release-facts dd {
  margin: 2px 0 0;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.release-state {
  margin-top: 23px;
}

.proof-sheet {
  min-width: 0;
  padding: clamp(20px, 3vw, 34px);
  border-radius: 14px;
  background: #153c30;
  color: var(--proof-ink);
}

.proof-sheet h2 {
  font-size: clamp(1.3rem, 1.9vw, 1.75rem);
}

.proof-station {
  margin-top: 17px;
  font-size: 1.12rem;
  font-weight: 650;
  overflow-wrap: anywhere;
}

.proof-times {
  display: grid;
  gap: 2px;
  margin-top: 3px;
  color: var(--proof-muted);
  font-size: 0.95rem;
  font-variant-numeric: tabular-nums;
}

.proof-values, .online-values {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
}

.proof-values {
  margin-top: 19px;
  padding-block: 13px 10px;
  border-top: 1px solid var(--proof-line);
  border-bottom: 1px solid var(--proof-line);
}

.proof-values > div + div, .online-values > div + div {
  border-inline-start: 1px solid var(--report-line);
}

.proof-values > div + div {
  padding-inline-start: clamp(8px, 1.5vw, 18px);
  border-color: var(--proof-line);
}

.proof-values dt, .proof-footer, .proof-empty {
  color: var(--proof-muted);
}

.proof-values dd, .online-values dd {
  margin: 0;
  font-size: clamp(1.45rem, 2.8vw, 2.35rem);
  line-height: 1.25;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}

.proof-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 7px 14px;
  margin-top: 12px;
  font-size: 0.94rem;
}

.proof-footer a, .evidence-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: fit-content;
  font-weight: 650;
}

.proof-footer a {
  color: var(--proof-ink);
}

.proof-footer a:focus-visible {
  outline-color: var(--proof-ink);
}

.proof-footer svg, .evidence-link svg {
  flex: none;
}

.proof-empty {
  margin-top: 17px;
}

.experiment-section {
  padding-top: clamp(24px, 3vw, 40px);
  border-top: 1px solid var(--report-line);
}

.section-context {
  margin-top: 7px;
  font-size: 0.93rem;
  color: var(--report-muted);
  font-variant-numeric: tabular-nums;
}

.weather-gain {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 5px 13px;
  margin-top: 18px;
  color: var(--brand-strong);
}

.weather-gain strong {
  font-size: clamp(1.9rem, 3vw, 2.6rem);
  line-height: 1.1;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
}

.section-text {
  max-width: 46ch;
  margin-top: 11px;
  color: var(--report-muted);
  line-height: 1.75;
}

.model-context {
  margin-top: 10px;
  color: var(--report-muted);
  font-size: 0.9rem;
  overflow-wrap: anywhere;
}

.experiment-copy .evidence-link {
  margin-top: 14px;
}

.error-figure {
  min-width: 0;
  margin: 0;
  padding: clamp(16px, 2.7vw, 26px);
  border: 1px solid var(--report-line);
  border-radius: 12px;
  background: var(--surface);
}

.error-figure figcaption {
  display: grid;
  gap: 2px;
}

.error-figure figcaption strong {
  font-size: 1.08rem;
}

.error-figure figcaption span, .bar-scale, .figure-note {
  color: var(--report-muted);
  font-size: 0.93rem;
}

.error-bars {
  display: grid;
  gap: 10px;
  margin: 17px 0 0;
  padding: 0;
  list-style: none;
}

.error-bars > li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: baseline;
  gap: 4px 8px;
}

.error-bars strong {
  font-variant-numeric: tabular-nums;
  font-weight: 650;
}

.error-bars .featured {
  color: var(--brand-strong);
  font-weight: 650;
}

.bar-track {
  grid-column: 1 / -1;
  height: 9px;
  overflow: hidden;
  background: #edf1eb;
}

.bar-track span {
  display: block;
  height: 100%;
  background: #778d80;
}

.featured .bar-track span {
  background: var(--brand);
}

.bar-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-variant-numeric: tabular-nums;
}

.figure-note {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--report-line);
}

.online-section {
  padding: clamp(19px, 3vw, 34px);
  border-radius: 14px;
  background: #e8f1e9;
}

.online-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: start;
  justify-content: space-between;
  gap: 9px 16px;
}

.online-values {
  margin-top: 17px;
  padding-block: 15px;
  border-top: 1px solid #c6d8ca;
  border-bottom: 1px solid #c6d8ca;
}

.online-values dt {
  color: var(--report-muted);
}

.online-values dd {
  color: var(--brand-strong);
}

.online-values dd span {
  font-size: 0.92rem;
  font-weight: 500;
}

.online-values > div + div {
  padding-inline-start: clamp(8px, 2.5vw, 24px);
  border-color: #c6d8ca;
}

.online-note {
  max-width: 72ch;
  margin-top: 13px;
  color: var(--report-muted);
  line-height: 1.75;
}

@media (max-width: 1100px) {
  .achievement-lead, .experiment-section { gap: 26px; }
}

@media (max-width: 680px) {
  .achievement-lead, .experiment-section {
    grid-template-columns: minmax(0, 1fr);
    gap: 18px;
  }

  .title-break { display: none; }

  .lead-text { margin-top: 12px; }
  .release-facts { margin-top: 18px; }
  .proof-values dt { font-size: 0.93rem; }
  .online-values { grid-template-columns: minmax(0, 1fr); }
  .online-values > div {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 2px 8px;
  }

  .online-values > div + div {
    margin-top: 8px;
    padding: 8px 0 0;
    border-inline-start: 0;
    border-top: 1px solid #c6d8ca;
  }
}
</style>
