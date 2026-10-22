export async function api(path, params = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined))
  const response = await fetch(`/api/${path}${query.size ? '?' + query : ''}`)
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || '加载失败，请稍后重试')
  return body
}
export const fmt = (value, digits = 1) => value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
export const colors = ['#176e59', '#d59c56', '#7198a4', '#b08076', '#a7ae76', '#a18baa']
export const models = { best: '自动择优', persistence: '持续性基线', rf: '随机森林', gbt: '梯度提升树' }
export const cityNames = { beijing: '北京', tianjin: '天津', langfang: '廊坊', baoding: '保定', tangshan: '唐山', zhangjiakou: '张家口' }
export const baseChart = {
  animationDuration: 350, color: colors, textStyle: { fontFamily: 'Segoe UI, Microsoft YaHei, sans-serif', color: '#65756e', fontSize: 11 },
  tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#e3e9e4', padding: 12, textStyle: { color: '#283c34', fontSize: 12 } },
  grid: { top: 24, left: 48, right: 22, bottom: 30 },
  xAxis: { axisLine: { lineStyle: { color: '#e4eae4' } }, axisTick: { show: false }, axisLabel: { color: '#839088' } },
  yAxis: { type: 'value', name: 'μg/m³', nameTextStyle: { color: '#8b968e', padding: [0, 0, 0, 24] }, axisLabel: { color: '#839088' }, splitLine: { lineStyle: { color: '#edf0ec', type: 'dashed' } } },
}
export function lineOption(series, { zoom = false } = {}) {
  const times = series[0]?.points.map(p => p.time) || []
  return {
    ...baseChart,
    grid: { ...baseChart.grid, bottom: zoom ? 52 : 30 },
    xAxis: { ...baseChart.xAxis, type: 'category', boundaryGap: false, data: times, axisLabel: { color: '#839088', formatter: value => value.length > 10 ? value.slice(5, 16) : value } },
    yAxis: { ...baseChart.yAxis },
    dataZoom: zoom ? [{ type: 'inside' }, { type: 'slider', height: 13, bottom: 4, borderColor: 'transparent', backgroundColor: '#f1f4ef', fillerColor: '#176e5918', handleSize: 12, textStyle: { color: '#95a098' } }] : [],
    series: series.map((s, i) => ({ name: s.name || cityNames[s.city_id], type: 'line', data: s.points.map(p => p.value === null ? null : +Number(p.value).toFixed(2)), showSymbol: false, connectNulls: false, lineStyle: { width: s.city_id === 'beijing' ? 2.7 : 1.5, opacity: i ? .72 : 1 }, emphasis: { focus: 'series' }, itemStyle: { color: colors[Object.keys(cityNames).indexOf(s.city_id)] || colors[i] }, areaStyle: s.city_id === 'beijing' ? { color: '#176e5910' } : undefined })),
  }
}
export function featureLabel(name) {
  let text = name
  for (const [id, label] of Object.entries(cityNames)) text = text.replace(id + '_', label + ' · ')
  const words = { pm25: 'PM₂.₅', pm10: 'PM₁₀', temperature_2m: '气温', relative_humidity_2m: '湿度', surface_pressure: '气压', wind_speed_10m: '风速', wind_direction_sin: '风向 sin', wind_direction_cos: '风向 cos', precipitation: '降水', mean: '均值', count: '有效数', lag: '滞后', day_of_week: '星期周期', hour: '小时周期', month: '月份周期' }
  for (const [word, label] of Object.entries(words)) text = text.replace(word, label)
  return text.replace(/_/g, ' ')
}
