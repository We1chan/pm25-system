<script setup>
/*
 * ECharts 图表容器。
 * 传入完整的 option；option 变化时整体替换（notMerge），避免旧系列残留。
 * 容器尺寸为 0（如所在面板被折叠）时先不初始化，等尺寸可测量后再画。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: { type: Object, default: null },
  height: { type: String, default: '300px' },
  label: { type: String, default: '数据图表' },
})

const emit = defineEmits(['select'])

const element = ref(null)
let chart = null
let observer = null
let frame = 0

function measurable() {
  return element.value?.clientWidth > 0 && element.value?.clientHeight > 0
}

function render() {
  if (!measurable()) {
    return
  }
  if (!chart) {
    chart = echarts.init(element.value)
    chart.on('click', event => emit('select', event))
  }
  if (props.option) {
    chart.setOption(props.option, { notMerge: true })
  }
}

onMounted(() => {
  observer = new ResizeObserver(() => {
    cancelAnimationFrame(frame)
    frame = requestAnimationFrame(() => {
      if (!chart) {
        render()
      } else if (!chart.isDisposed()) {
        chart.resize()
      }
    })
  })
  observer.observe(element.value)
  render()
})

watch(() => props.option, render)

onBeforeUnmount(() => {
  observer?.disconnect()
  cancelAnimationFrame(frame)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="element" class="chart" :style="{ height }" role="img" :aria-label="label"></div>
</template>

<style scoped>
.chart {
  width: 100%;
  min-width: 0;
}
</style>
