/*
 * 后端接口访问。
 * 所有请求都走同源的 /api 前缀（开发时由 Vite 代理到 8000 端口）。
 * 请求失败时抛出后端给出的中文 detail，页面原样展示，不吞掉错误。
 */

// 去掉未选择的参数（undefined、null、空字符串），避免把"全部"误当成筛选条件
function buildQuery(params) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') {
      continue
    }
    query.set(key, value)
  }
  const text = query.toString()
  return text ? `?${text}` : ''
}

// 业务错误的 detail 是中文字符串；FastAPI 参数校验错误的 detail 是数组，这里统一成一句话
function errorMessage(body, status) {
  const detail = body?.detail
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail) && detail.length) {
    const reasons = detail.map(item => item.msg).join('；')
    return `请求参数不正确：${reasons}`
  }
  return `请求失败（HTTP ${status}），请稍后重试`
}

async function request(method, path, params) {
  let response
  try {
    response = await fetch(`/api/${path}${buildQuery(params)}`, { method })
  } catch {
    throw new Error('无法连接后端服务，请确认系统已经启动')
  }
  let body = null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  if (!response.ok) {
    throw new Error(errorMessage(body, response.status))
  }
  return body
}

export function api(path, params = {}) {
  return request('GET', path, params)
}

export function postApi(path, params = {}) {
  return request('POST', path, params)
}

// 生成下载链接（CSV 导出由浏览器直接下载，不经过 fetch）
export function apiHref(path, params = {}) {
  return `/api/${path}${buildQuery(params)}`
}
