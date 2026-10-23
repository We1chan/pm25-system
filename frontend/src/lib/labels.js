/*
 * 界面中文名称：城市、模型、气象变量、浓度分组和特征名。
 * 后端返回的是英文标识（如 beijing、tcn72），统一在这里翻译，页面不各自硬编码。
 */

export const cityNames = {
  beijing: '北京',
  tianjin: '天津',
  langfang: '廊坊',
  baoding: '保定',
  tangshan: '唐山',
  zhangjiakou: '张家口',
}

export const cityIds = Object.keys(cityNames)

// 第一代城市版的模型
export const cityModelNames = {
  best: '自动择优（按验证集）',
  persistence: '持续性基线',
  rf: 'Spark 随机森林',
  gbt: 'Spark 梯度提升树',
}

// 第二代站点版的模型
export const stationModelNames = {
  best: '自动择优（按验证集）',
  tcn72: 'CUDA 时序卷积 TCN',
  rf: 'Spark 随机森林',
  persistence: '持续性基线',
}

// 气象变量：名称与单位
export const weatherVariables = {
  wind_speed_10m: { name: '风速', unit: 'm/s' },
  temperature_2m: { name: '气温', unit: '°C' },
  relative_humidity_2m: { name: '相对湿度', unit: '%' },
  surface_pressure: { name: '气压', unit: 'hPa' },
  precipitation: { name: '降水', unit: 'mm' },
  wind_direction_10m: { name: '风向', unit: '°' },
}

// 第三代离线测试报告中的浓度分组键
export const regimeNames = {
  pm_lt35: '低浓度 <35',
  pm_35_75: '中浓度 35–75',
  pm_ge75: '高浓度 ≥75',
  abrupt_ge20: '浓度突变 ≥20',
}

// 实时刷新的各个阶段，顺序即流水线顺序
export const refreshSteps = [
  { id: 'collecting', name: '采集实测与天气' },
  { id: 'spark', name: 'HDFS + Spark 处理' },
  { id: 'inference', name: 'TCN 推理与发布' },
  { id: 'complete', name: '完成' },
]

export const refreshPhaseText = {
  initializing: '正在初始化实时连接',
  collecting: '正在采集最新实测和天气资料',
  spark: '正在用 Spark 清洗数据并构建 72 小时特征',
  inference: '正在运行 TCN 并发布未来六小时预测',
  complete: '更新完成',
  failed: '本轮更新未完成',
}

const pollutantNames = {
  pm25: 'PM₂.₅',
  pm10: 'PM₁₀',
  so2: 'SO₂',
  no2: 'NO₂',
  o3: 'O₃',
  co: 'CO',
}

const plainFeatureNames = {
  temperature_2m: '气温',
  relative_humidity_2m: '湿度',
  surface_pressure: '气压',
  wind_speed_10m: '风速',
  precipitation: '降水',
  wind_direction_sin: '风向 sin',
  wind_direction_cos: '风向 cos',
  hour_sin: '小时周期 sin',
  hour_cos: '小时周期 cos',
  month_sin: '月份周期 sin',
  month_cos: '月份周期 cos',
  day_of_week_sin: '星期周期 sin',
  day_of_week_cos: '星期周期 cos',
}

// 把 Spark 特征列名翻译成中文，例如 beijing_pm25_lag_3h → 北京 · PM₂.₅ 3 小时前
export function featureLabel(name) {
  let rest = name
  let prefix = ''
  for (const [id, label] of Object.entries(cityNames)) {
    if (rest.startsWith(`${id}_`)) {
      prefix = `${label} · `
      rest = rest.slice(id.length + 1)
      break
    }
  }
  if (plainFeatureNames[rest]) {
    return prefix + plainFeatureNames[rest]
  }
  const windowMatch = rest.match(/^(pm25|pm10|so2|no2|o3|co)_(lag|mean|count)_(\d+)h$/)
  if (windowMatch) {
    const pollutant = pollutantNames[windowMatch[1]]
    const hours = windowMatch[3]
    if (windowMatch[2] === 'lag') {
      return `${prefix}${pollutant} ${hours} 小时前`
    }
    if (windowMatch[2] === 'mean') {
      return `${prefix}${pollutant} 近 ${hours} 小时均值`
    }
    return `${prefix}${pollutant} 近 ${hours} 小时有效数`
  }
  if (pollutantNames[rest]) {
    return `${prefix}${pollutantNames[rest]} 当前`
  }
  return prefix + rest.replace(/_/g, ' ')
}
