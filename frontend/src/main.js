import { createApp } from 'vue'
import * as echarts from 'echarts'
import App from './App.vue'
import './style.css'
try {
  const response = await fetch('/region.geojson')
  if (response.ok) echarts.registerMap('bth-region', await response.json())
} catch (error) { console.warn('区域边界暂不可用', error) }
createApp(App).mount('#app')
