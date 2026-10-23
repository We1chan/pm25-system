/*
 * 数字与时间的显示格式。
 * 系统所有时间都是北京时间（UTC+8）：实时接口返回带 +08:00 的 ISO 字符串，
 * 历史接口返回不带时区的北京时间字符串。这里两种都按北京时间显示，
 * 与浏览器所在电脑的时区设置无关。
 */

export const EMPTY = '—'

const TIME_ZONE = 'Asia/Shanghai'

export function isNumber(value) {
  if (value === null || value === undefined || value === '') {
    return false
  }
  return Number.isFinite(Number(value))
}

// 千分位 + 固定小数位；缺失值显示破折号，表示暂无数据，而不是 0
export function fmt(value, digits = 1) {
  if (!isNumber(value)) {
    return EMPTY
  }
  return Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtInt(value) {
  return fmt(value, 0)
}

// 把 0—1 的比例显示为百分数
export function fmtPercent(ratio, digits = 1) {
  if (!isNumber(ratio)) {
    return EMPTY
  }
  return `${fmt(Number(ratio) * 100, digits)}%`
}

export function fmtSigned(value, digits = 1) {
  if (!isNumber(value)) {
    return EMPTY
  }
  const sign = Number(value) > 0 ? '+' : ''
  return `${sign}${fmt(value, digits)}`
}

// 字节数按十进制换算（与 README 一致：1 GB = 10⁹ 字节）
export function fmtBytes(bytes) {
  if (!isNumber(bytes)) {
    return EMPTY
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = Number(bytes)
  let index = 0
  while (value >= 1000 && index < units.length - 1) {
    value /= 1000
    index += 1
  }
  const digits = index === 0 ? 0 : value >= 100 ? 0 : value >= 10 ? 1 : 2
  return `${fmt(value, digits)} ${units[index]}`
}

export function fmtDuration(seconds) {
  if (!isNumber(seconds)) {
    return EMPTY
  }
  const total = Number(seconds)
  if (total < 90) {
    return `${fmt(total, 0)} 秒`
  }
  return `${fmt(total / 60, 1)} 分钟`
}

const partsFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

const NAIVE_TIME = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2})(?::(\d{2}))?(?::\d{2}(?:\.\d+)?)?)?$/

// 拆出北京时间的年月日时分；无时区字符串本身就是北京时间，直接拆分
function beijingParts(value) {
  if (value === null || value === undefined || value === '') {
    return null
  }
  if (typeof value === 'string') {
    const match = value.match(NAIVE_TIME)
    if (match) {
      return {
        year: match[1],
        month: match[2],
        day: match[3],
        hour: match[4] ?? '00',
        minute: match[5] ?? '00',
      }
    }
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }
  const parts = {}
  for (const part of partsFormatter.formatToParts(date)) {
    parts[part.type] = part.value
  }
  return parts
}

// 月-日 时:分，例如 10-23 00:32
export function bjDateTime(value) {
  const p = beijingParts(value)
  return p ? `${p.month}-${p.day} ${p.hour}:${p.minute}` : EMPTY
}

// 年-月-日 时:分
export function bjFull(value) {
  const p = beijingParts(value)
  return p ? `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}` : EMPTY
}

export function bjTime(value) {
  const p = beijingParts(value)
  return p ? `${p.hour}:${p.minute}` : EMPTY
}

export function bjDate(value) {
  const p = beijingParts(value)
  return p ? `${p.year}-${p.month}-${p.day}` : EMPTY
}

// 北京时间的某一天（YYYY-MM-DD），offsetDays 为相对今天的天数
export function beijingDay(offsetDays = 0) {
  const date = new Date(Date.now() + offsetDays * 86400000)
  return bjDate(date)
}

// 两个时刻相差的分钟数（b 缺省为现在）
export function minutesSince(value, now = Date.now()) {
  if (!value) {
    return null
  }
  return (now - new Date(value).getTime()) / 60000
}
