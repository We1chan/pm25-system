/*
 * 页面之间共享的少量状态。
 * - historyYear：第一代城市研究页面（概览、分析、质量）共用的年份，切换页面时保持不变。
 * - loadHistoryMeta：/api/meta 只请求一次，供需要城市坐标、年份范围和回放区间的页面复用。
 */
import { ref } from 'vue'
import { api } from './api'

export const historyYear = ref('2025')

let metaRequest = null

export function loadHistoryMeta() {
  if (!metaRequest) {
    // 失败时清掉缓存，下次进入页面可以重试
    metaRequest = api('meta').catch(error => {
      metaRequest = null
      throw error
    })
  }
  return metaRequest
}
