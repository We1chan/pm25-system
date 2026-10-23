/*
 * 前端入口：注册京津冀行政边界地图，然后挂载应用。
 * 边界文件读取失败不影响启动，地图会退化为经纬度散点图。
 */
import { createApp } from 'vue'
import * as echarts from 'echarts'
import App from './App.vue'
import { REGION_MAP } from './lib/chart'
import './styles/base.css'
import './styles/layout.css'
import './styles/components.css'

try {
  const response = await fetch('/region.geojson')
  if (response.ok) {
    echarts.registerMap(REGION_MAP, await response.json())
  }
} catch (error) {
  console.warn('区域边界暂不可用，地图改用经纬度散点显示', error)
}

createApp(App).mount('#app')
