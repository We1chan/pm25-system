/*
 * 图表统一主题与常用配置片段（ECharts）。
 *
 * 配色规则：
 * - 颜色跟着"实体"走，不跟着排名走：同一个模型、同一个城市在所有页面颜色相同。
 * - 实测值（真实答案）统一用深灰，基线用浅灰虚线，模型用彩色。
 * - 六个分类色的顺序经过色觉障碍区分校验（白底，相邻两色可区分）。
 *
 * 时间轴规则：
 * 所有时间先换算成"用 UTC 表示的北京墙钟时间"，再让 ECharts 用 UTC 显示（useUTC），
 * 这样无论演示电脑的时区怎么设置，坐标轴上都是北京时间。
 */
import * as echarts from 'echarts'
import { fmt } from './format'

const FONT = '"Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif'

export const ink = {
  primary: '#15211c',
  secondary: '#46534d',
  muted: '#737e78',
  grid: '#e8ece8',
  axis: '#c9d1ca',
}

// 分类色（按此顺序使用）
export const palette = {
  green: '#0b8a5f',
  blue: '#2a78d6',
  orange: '#eb6834',
  violet: '#4a3aa7',
  yellow: '#eda100',
  magenta: '#e87ba4',
}

export const roleColors = {
  observed: '#2b3632',
  baseline: '#9a9f99',
  forecast: palette.green,
}

// 模型颜色：TCN 绿、随机森林蓝、梯度提升树橙、持续性基线灰
export const modelColors = {
  tcn72: palette.green,
  tcn: palette.green,
  rf: palette.blue,
  gbt: palette.orange,
  persistence: roleColors.baseline,
}

export const cityColors = {
  beijing: palette.green,
  tianjin: palette.blue,
  langfang: palette.orange,
  baoding: palette.violet,
  tangshan: palette.yellow,
  zhangjiakou: palette.magenta,
}

// 单一绿色由浅到深，用于热力图等连续量
export const greenRamp = [
  '#eef6f1',
  '#cfe7da',
  '#a2d0b9',
  '#6db394',
  '#3a9271',
  '#127452',
  '#0a573c',
]

// PM2.5 小时浓度分档，只用于地图点的着色；35、75 与在线核验的浓度分组一致
export const pmBins = [
  { max: 35, color: '#3a9d6c', label: '<35' },
  { max: 75, color: '#d6ae2f', label: '35–75' },
  { max: 115, color: '#e8853a', label: '75–115' },
  { max: 150, color: '#d4504b', label: '115–150' },
  { max: Infinity, color: '#8a3d86', label: '≥150' },
]

const MISSING_COLOR = '#b9c0ba'

export function pmColor(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return MISSING_COLOR
  }
  return pmBins.find(bin => Number(value) < bin.max).color
}

// ---------- 时间 ----------

const BEIJING_OFFSET_MS = 8 * 3600 * 1000
const ZONED = /([zZ]|[+-]\d{2}:?\d{2})$/

// 北京时间字符串 → 坐标轴数值（毫秒）。支持带时区 ISO、"YYYY-MM-DD HH:MM:SS"、"YYYY-MM-DD"、"YYYY-MM"
export function axisTime(text) {
  if (!text) {
    return null
  }
  if (ZONED.test(text)) {
    return Date.parse(text) + BEIJING_OFFSET_MS
  }
  const [datePart, clockPart = '00:00:00'] = text.replace('T', ' ').split(' ')
  const dateFields = datePart.split('-')
  while (dateFields.length < 3) {
    dateFields.push('01')
  }
  const clockFields = clockPart.split(':')
  while (clockFields.length < 3) {
    clockFields.push('00')
  }
  return Date.parse(`${dateFields.join('-')}T${clockFields.join(':')}Z`)
}

function pad(number) {
  return String(number).padStart(2, '0')
}

// 坐标轴数值 → 文字。precision：minute 为 "MM-DD HH:mm"，day 为 "YYYY-MM-DD"，month 为 "YYYY-MM"
export function axisTimeLabel(ms, precision = 'minute') {
  const date = new Date(ms)
  const year = date.getUTCFullYear()
  const month = pad(date.getUTCMonth() + 1)
  const day = pad(date.getUTCDate())
  if (precision === 'month') {
    return `${year}-${month}`
  }
  if (precision === 'day') {
    return `${year}-${month}-${day}`
  }
  return `${month}-${day} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
}

// ---------- 基础配置 ----------

export function baseOption() {
  return {
    animationDuration: 300,
    useUTC: true,
    textStyle: { fontFamily: FONT, color: ink.secondary, fontSize: 12 },
    // 顶部留出图例（第一行）和纵轴单位（第二行）的位置
    grid: { top: 54, left: 52, right: 20, bottom: 30 },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: '#fff',
      borderColor: ink.axis,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: ink.primary, fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: ink.axis } },
    },
  }
}

export function legend(names, extra = {}) {
  return {
    data: names,
    top: 0,
    left: 0,
    icon: 'roundRect',
    itemWidth: 14,
    itemHeight: 8,
    itemGap: 18,
    textStyle: { color: ink.secondary, fontSize: 12 },
    ...extra,
  }
}

export function valueAxis(name = 'μg/m³', extra = {}) {
  return {
    type: 'value',
    name,
    nameGap: 14,
    nameTextStyle: { color: ink.muted, fontSize: 11, align: 'left', padding: [0, 0, 0, -36] },
    axisLabel: { color: ink.muted, fontSize: 11 },
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: ink.grid } },
    ...extra,
  }
}

export function timeAxis(extra = {}) {
  return {
    type: 'time',
    axisLine: { lineStyle: { color: ink.axis } },
    axisTick: { show: false },
    splitLine: { show: false },
    axisLabel: {
      color: ink.muted,
      fontSize: 11,
      hideOverlap: true,
      formatter: {
        year: '{yyyy}年',
        month: '{M}月',
        day: '{MM}-{dd}',
        hour: '{HH}:{mm}',
        minute: '{HH}:{mm}',
        second: '{HH}:{mm}',
        millisecond: '{HH}:{mm}',
      },
    },
    ...extra,
  }
}

export function categoryAxis(data, extra = {}) {
  return {
    type: 'category',
    data,
    axisLine: { lineStyle: { color: ink.axis } },
    axisTick: { show: false },
    axisLabel: { color: ink.muted, fontSize: 11 },
    ...extra,
  }
}

// 底部时间缩放条；使用时把 grid.bottom 调大到 60 左右
export function zoomControls(start = 0) {
  return [
    { type: 'inside', start, end: 100 },
    {
      type: 'slider',
      start,
      end: 100,
      height: 18,
      bottom: 8,
      showDetail: false,
      borderColor: ink.grid,
      fillerColor: 'rgba(10, 110, 79, 0.10)',
      handleStyle: { color: '#fff', borderColor: ink.axis },
      moveHandleSize: 0,
      dataBackground: {
        lineStyle: { color: ink.axis },
        areaStyle: { color: ink.grid },
      },
    },
  ]
}

// ---------- 系列 ----------

export function lineSeries(options) {
  const {
    name,
    data,
    color,
    width = 2,
    dashed = false,
    points = false,
    area = false,
    z = 2,
    ...extra
  } = options
  return {
    name,
    type: 'line',
    data,
    z,
    connectNulls: false,
    showSymbol: points,
    symbol: 'circle',
    symbolSize: 8,
    lineStyle: { color, width, type: dashed ? 'dashed' : 'solid', cap: 'round', join: 'round' },
    itemStyle: { color, borderColor: '#fff', borderWidth: 2 },
    areaStyle: area ? { color, opacity: 0.1 } : undefined,
    emphasis: { disabled: true },
    ...extra,
  }
}

export function barSeries(options) {
  const { name, data, color, width = 24, labels = false, digits = 2, ...extra } = options
  return {
    name,
    type: 'bar',
    data,
    barMaxWidth: width,
    itemStyle: { color, borderRadius: [4, 4, 0, 0] },
    label: labels
      ? {
          show: true,
          position: 'top',
          color: ink.secondary,
          fontSize: 11,
          formatter: item => fmt(Array.isArray(item.value) ? item.value[1] : item.value, digits),
        }
      : undefined,
    emphasis: { disabled: true },
    ...extra,
  }
}

export const BAND_NAME = '80% 区间'

// 预测区间色带：用"下沿 + (上沿−下沿)"两条堆叠线实现，下沿那条不显示也不进提示框
export function bandSeries(lower, upper, color = palette.green) {
  const width = upper.map((point, index) => [point[0], point[1] - lower[index][1]])
  const hidden = {
    symbol: 'none',
    silent: true,
    lineStyle: { opacity: 0 },
    emphasis: { disabled: true },
  }
  return [
    { ...hidden, name: '__lower', type: 'line', stack: 'band', data: lower, z: 1 },
    {
      ...hidden,
      name: BAND_NAME,
      type: 'line',
      stack: 'band',
      data: width,
      z: 1,
      itemStyle: { color, opacity: 0.25 },
      areaStyle: { color, opacity: 0.16 },
    },
  ]
}

export function referenceLine(value, label) {
  return {
    silent: true,
    symbol: 'none',
    lineStyle: { color: ink.muted, type: 'dashed', width: 1 },
    label: { formatter: label, color: ink.muted, fontSize: 11, position: 'insideEndTop' },
    data: [{ yAxis: value }],
  }
}

// ---------- 提示框 ----------

const HALF_HOUR = 30 * 60 * 1000

function tooltipRow(marker, name, text) {
  return (
    '<div style="display:flex;justify-content:space-between;gap:14px;line-height:1.8">' +
    `<span>${marker}${name}</span><b style="font-weight:600">${text}</b></div>`
  )
}

/*
 * 时间轴提示框：表头显示北京时间，每行显示一条系列的值。
 * 时间轴上各系列的点不一定对齐，只显示与指针时刻相同（±半小时）的点，
 * 避免把别的时刻的值误显示在这一时刻。
 */
export function timeTooltip({ unit = 'μg/m³', digits = 1, precision = 'minute' } = {}) {
  return params => {
    const list = Array.isArray(params) ? params : [params]
    if (!list.length) {
      return ''
    }
    const at = list[0].axisValue
    const rows = []
    for (const item of list) {
      if (item.seriesName.startsWith('__') || item.seriesName === BAND_NAME) {
        continue
      }
      const pair = Array.isArray(item.value) ? item.value : null
      if (!pair || Math.abs(pair[0] - at) > HALF_HOUR) {
        continue
      }
      if (pair[1] === null || pair[1] === undefined) {
        continue
      }
      let text = `${fmt(pair[1], digits)} ${unit}`
      const lower = item.data?.lower
      const upper = item.data?.upper
      if (lower !== null && lower !== undefined && upper !== null && upper !== undefined) {
        const range = `${fmt(lower, digits)}–${fmt(upper, digits)}`
        text += `<span style="font-weight:400;color:${ink.muted}">（区间 ${range}）</span>`
      }
      rows.push(tooltipRow(item.marker, item.seriesName, text))
    }
    const prefix = precision === 'minute' ? '北京时间 ' : ''
    const label = axisTimeLabel(at, precision)
    const head = `<div style="color:${ink.muted};margin-bottom:2px">${prefix}${label}</div>`
    return head + (rows.length ? rows.join('') : '<div>该时刻没有数据</div>')
  }
}

// 类目轴提示框
export function categoryTooltip({ unit = 'μg/m³', digits = 1, title } = {}) {
  return params => {
    const list = Array.isArray(params) ? params : [params]
    if (!list.length) {
      return ''
    }
    const rows = list
      .filter(item => !item.seriesName.startsWith('__'))
      .map(item => {
        const raw = Array.isArray(item.value) ? item.value[1] : item.value
        const text = raw === null || raw === undefined ? '暂无数据' : `${fmt(raw, digits)} ${unit}`
        return tooltipRow(item.marker, item.seriesName, text)
      })
    const label = title ? title(list[0].axisValueLabel) : list[0].axisValueLabel
    return `<div style="color:${ink.muted};margin-bottom:2px">${label}</div>${rows.join('')}`
  }
}

// ---------- 地图 ----------

export const REGION_MAP = 'bth-region'

export function hasRegionMap() {
  return Boolean(echarts.getMap(REGION_MAP))
}

/*
 * 站点/城市点位地图。points: [{ id, name, lon, lat, value }]。
 * 点的颜色按 PM2.5 浓度分档；只给选中的点加文字标签，避免市区站点标签互相遮挡。
 * 地图边界文件读取失败时，退化为经纬度散点图，功能不受影响。
 */
export function pointMapOption(options) {
  const {
    points,
    selectedId = null,
    center,
    zoom = 1,
    highlight = [],
    labelAll = false,
    sizeOf = () => 12,
  } = options
  const data = points.map(point => {
    const selected = point.id === selectedId
    return {
      id: point.id,
      name: point.name,
      value: [point.lon, point.lat, point.value],
      symbolSize: selected ? sizeOf(point) + 6 : sizeOf(point),
      itemStyle: {
        color: pmColor(point.value),
        borderColor: selected ? ink.primary : '#ffffff',
        borderWidth: 2,
      },
      label: { show: labelAll || selected },
      z: selected ? 5 : 3,
    }
  })
  const scatter = {
    type: 'scatter',
    data,
    label: {
      position: 'right',
      formatter: item => (labelAll ? `${item.name} ${fmt(item.value[2], 0)}` : item.name),
      color: ink.primary,
      fontSize: 12,
      backgroundColor: 'rgba(255, 255, 255, 0.88)',
      padding: [2, 6],
      borderRadius: 4,
    },
    labelLayout: { hideOverlap: true },
    emphasis: { scale: 1.3 },
  }
  const tooltip = {
    trigger: 'item',
    confine: true,
    backgroundColor: '#fff',
    borderColor: ink.axis,
    textStyle: { color: ink.primary, fontSize: 12 },
    formatter: item => {
      const value = item.value?.[2]
      const text = value === null || value === undefined ? '暂无实测' : `${fmt(value)} μg/m³`
      return `${item.name}<br/>PM₂.₅ <b>${text}</b>`
    },
  }
  if (!hasRegionMap()) {
    return {
      ...baseOption(),
      tooltip,
      xAxis: valueAxis('经度', { scale: true }),
      yAxis: valueAxis('纬度', { scale: true }),
      series: [scatter],
    }
  }
  return {
    textStyle: { fontFamily: FONT },
    tooltip,
    geo: {
      map: REGION_MAP,
      roam: true,
      center,
      zoom,
      scaleLimit: { min: 0.8, max: 16 },
      layoutCenter: ['50%', '50%'],
      layoutSize: '100%',
      itemStyle: { areaColor: '#eef1ec', borderColor: '#c9d1ca', borderWidth: 1 },
      emphasis: { disabled: true },
      select: { disabled: true },
      regions: highlight.map(name => ({ name, itemStyle: { areaColor: '#e1ebe2' } })),
    },
    series: [{ ...scatter, coordinateSystem: 'geo' }],
  }
}
